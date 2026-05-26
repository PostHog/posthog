import { logger } from '../../utils/logger'

/**
 * Owns a service's lifecycle. `start()` produces the service instance plus
 * a `stop` callback that tears it down. Anyone holding the service only
 * sees the business interface — the start/stop pair stays with the
 * Manager. This lets the lifecycle plumb dependencies (services, pools,
 * config) through a single services map without each entry needing to wear
 * a start/stop hat.
 */
export interface Manager<T> {
    start(): Promise<{ service: T; stop: () => Promise<void> }>
}

type ServiceOf<M> = M extends Manager<infer T> ? T : never

/** Internal entry captured at registration time. */
interface RegisteredManager {
    name: string
    manager: Manager<unknown>
}

/**
 * Per-lifecycle accumulator. `register` records a `Manager` for each entry;
 * the corresponding service value lands in the services map only after the
 * lifecycle starts. Until then, the builder is just a typed recipe.
 */
export class LifecycleBuilder<S extends Record<string, object> = Record<never, object>> {
    private constructor(readonly managers: ReadonlyArray<RegisteredManager>) {}

    static empty(): LifecycleBuilder<Record<never, object>> {
        return new LifecycleBuilder<Record<never, object>>([])
    }

    register<Name extends string, M extends Manager<object>>(
        name: Name & (Name extends keyof S ? never : Name),
        manager: M
    ): LifecycleBuilder<S & Record<Name, ServiceOf<M>>> {
        return new LifecycleBuilder<S & Record<Name, ServiceOf<M>>>([
            ...this.managers,
            { name, manager: manager as Manager<unknown> },
        ])
    }

    build(name: string): Lifecycle<S> {
        const runner = new ManagerRunner(name, this.managers)
        return new Lifecycle<S>(name, () => runner.getServices() as S, runner)
    }
}

/**
 * Legacy service shape — exposes `start()/stop()` directly on the
 * business object. Prefer the `Manager<T>` shape for new code; this is
 * kept for adapter use so existing services can be wired into a lifecycle
 * without refactoring their interface.
 */
export interface ConsumerManagedService {
    start(): Promise<void>
    stop(): Promise<void>
}

/**
 * Adapts a legacy service to the `Manager` shape. The adapted service is
 * exposed in the lifecycle's services map without its `start`/`stop`
 * methods.
 */
export function adaptManagedService<T extends ConsumerManagedService>(svc: T): Manager<Omit<T, 'start' | 'stop'>> {
    return {
        async start() {
            await svc.start()
            return {
                service: svc as Omit<T, 'start' | 'stop'>,
                stop: () => svc.stop(),
            }
        },
    }
}

/**
 * Returned by `Lifecycle.start()`. The handle's `stop` removes this caller
 * from the refcount and is single-shot — calling it twice has no effect
 * after the first call.
 */
export interface StartedLifecycle<S extends Record<string, object>> {
    readonly name: string
    readonly services: S
    readonly stop: () => Promise<void>
}

// ---------------------------------------------------------------------------
// Runner: pluggable "boot/teardown" implementation behind the state machine.

interface Runner {
    start(): Promise<void>
    stop(): Promise<void>
}

/**
 * Boots and tears down the ordered list of managers. Tracks which managers
 * successfully started so `stop` only tears those down. The started
 * services map is populated incrementally during start and torn down in
 * reverse on stop.
 */
class ManagerRunner implements Runner {
    private started: Array<{ name: string; service: object; stop: () => Promise<void> }> = []
    private servicesCache?: Record<string, object>

    constructor(
        private readonly lifecycleName: string,
        private readonly entries: ReadonlyArray<RegisteredManager>
    ) {}

    async start(): Promise<void> {
        const started: Array<{ name: string; service: object; stop: () => Promise<void> }> = []
        for (const entry of this.entries) {
            logger.info(`Lifecycle[${this.lifecycleName}]: starting ${entry.name}`)
            try {
                const { service, stop } = await entry.manager.start()
                started.push({ name: entry.name, service: service as object, stop })
            } catch (err) {
                logger.error(
                    `Lifecycle[${this.lifecycleName}]: ${entry.name} start failed, rolling back ${started.length} started service(s)`,
                    { error: err }
                )
                for (let i = started.length - 1; i >= 0; i--) {
                    try {
                        await started[i].stop()
                    } catch (rollbackErr) {
                        logger.error(
                            `Lifecycle[${this.lifecycleName}]: ${started[i].name} stop failed during rollback`,
                            { error: rollbackErr }
                        )
                    }
                }
                throw err
            }
        }
        this.started = started
        this.servicesCache = Object.fromEntries(started.map((s) => [s.name, s.service]))
    }

    async stop(): Promise<void> {
        const svcs = this.started
        this.started = []
        this.servicesCache = undefined
        for (let i = svcs.length - 1; i >= 0; i--) {
            logger.info(`Lifecycle[${this.lifecycleName}]: stopping ${svcs[i].name}`)
            try {
                await svcs[i].stop()
            } catch (err) {
                logger.error(`Lifecycle[${this.lifecycleName}]: ${svcs[i].name} stop failed`, { error: err })
                throw err
            }
        }
    }

    getServices(): Record<string, object> {
        if (!this.servicesCache) {
            throw new Error('lifecycle not started')
        }
        return this.servicesCache
    }
}

/**
 * Runs a child lifecycle on top of a parent lifecycle. On `start`: start
 * (or refcount onto) the parent, resolve its services, hand them to the
 * configure callback to build a child lifecycle, then start the child.
 * On `stop`: stop the child then release the parent. The parent boot is
 * shared across all chains rooted at it via the parent's own refcount.
 */
class ChainedRunner<SParent extends Record<string, object>, SChild extends Record<string, object>> implements Runner {
    private parentHandle?: StartedLifecycle<SParent>
    private childHandle?: StartedLifecycle<SChild>
    private servicesCache?: SParent & SChild

    constructor(
        private readonly parent: Lifecycle<SParent>,
        private readonly configure: (
            parentServices: SParent,
            builder: LifecycleBuilder<Record<never, object>>
        ) => LifecycleBuilder<SChild>,
        private readonly childName: string
    ) {}

    async start(): Promise<void> {
        logger.info(`Lifecycle[${this.childName}]: acquiring parent ${this.parent.name}`)
        const parentHandle = await this.parent.start()
        try {
            const childLifecycle = this.configure(parentHandle.services, LifecycleBuilder.empty()).build(this.childName)
            const childHandle = await childLifecycle.start()
            this.parentHandle = parentHandle
            this.childHandle = childHandle
            this.servicesCache = { ...parentHandle.services, ...childHandle.services }
        } catch (err) {
            logger.error(`Lifecycle[${this.childName}]: chain start failed, releasing parent ${this.parent.name}`, {
                error: err,
            })
            try {
                await parentHandle.stop()
            } catch (parentStopErr) {
                logger.error(`Lifecycle[${this.childName}]: parent ${this.parent.name} stop failed during rollback`, {
                    error: parentStopErr,
                })
            }
            throw err
        }
    }

    async stop(): Promise<void> {
        const childHandle = this.childHandle
        const parentHandle = this.parentHandle
        this.childHandle = undefined
        this.parentHandle = undefined
        this.servicesCache = undefined
        try {
            if (childHandle) {
                await childHandle.stop()
            }
        } finally {
            if (parentHandle) {
                logger.info(`Lifecycle[${this.childName}]: releasing parent ${this.parent.name}`)
                await parentHandle.stop()
            }
        }
    }

    getServices(): SParent & SChild {
        if (!this.servicesCache) {
            throw new Error(`chained lifecycle "${this.childName}" is not started`)
        }
        return this.servicesCache
    }
}

// ---------------------------------------------------------------------------
// Caller set: refcount with single-shot release callbacks.

class CallerSet {
    private callers = new Set<number>()
    private nextId = 0

    register(): () => boolean {
        const id = this.nextId++
        this.callers.add(id)
        let released = false
        return () => {
            if (released) {
                return false
            }
            released = true
            this.callers.delete(id)
            return true
        }
    }

    size(): number {
        return this.callers.size
    }
}

// ---------------------------------------------------------------------------
// State machine.

interface LifecycleContext {
    runStart(): Promise<void>
    runStop(): Promise<void>
    callerCount(): number
}

type Outcome =
    | { kind: 'transition'; next: LifecycleState }
    | { kind: 'wait'; on: Promise<unknown> }
    | { kind: 'done' }
    | { kind: 'failed'; next: LifecycleState; error: unknown }

interface LifecycleState {
    onStart(ctx: LifecycleContext): Outcome
    onStop(ctx: LifecycleContext): Outcome
}

class StoppedState implements LifecycleState {
    onStart(ctx: LifecycleContext): Outcome {
        return { kind: 'transition', next: new StartingState(ctx.runStart()) }
    }
    onStop(_ctx: LifecycleContext): Outcome {
        return { kind: 'done' }
    }
}

class StartingState implements LifecycleState {
    private settled: 'pending' | 'ok' | { error: unknown } = 'pending'
    private readonly waitOn: Promise<void>

    constructor(startPromise: Promise<void>) {
        this.waitOn = startPromise.then(
            () => {
                this.settled = 'ok'
            },
            (err: unknown) => {
                this.settled = { error: err }
            }
        )
    }

    onStart(_ctx: LifecycleContext): Outcome {
        return this.snapshot()
    }
    onStop(_ctx: LifecycleContext): Outcome {
        return this.snapshot()
    }

    private snapshot(): Outcome {
        if (this.settled === 'pending') {
            return { kind: 'wait', on: this.waitOn }
        }
        if (this.settled === 'ok') {
            return { kind: 'transition', next: new StartedState() }
        }
        return { kind: 'failed', next: new StoppedState(), error: this.settled.error }
    }
}

class StartedState implements LifecycleState {
    onStart(_ctx: LifecycleContext): Outcome {
        return { kind: 'done' }
    }
    onStop(ctx: LifecycleContext): Outcome {
        if (ctx.callerCount() === 0) {
            return { kind: 'transition', next: new StoppingState(ctx.runStop()) }
        }
        return { kind: 'done' }
    }
}

class StoppingState implements LifecycleState {
    private settled: 'pending' | 'ok' | { error: unknown } = 'pending'
    private readonly waitOn: Promise<void>

    constructor(stopPromise: Promise<void>) {
        this.waitOn = stopPromise.then(
            () => {
                this.settled = 'ok'
            },
            (err: unknown) => {
                this.settled = { error: err }
            }
        )
    }

    onStart(_ctx: LifecycleContext): Outcome {
        if (this.settled === 'pending') {
            return { kind: 'wait', on: this.waitOn }
        }
        return { kind: 'transition', next: new StoppedState() }
    }

    onStop(_ctx: LifecycleContext): Outcome {
        if (this.settled === 'pending') {
            return { kind: 'wait', on: this.waitOn }
        }
        if (this.settled === 'ok') {
            return { kind: 'transition', next: new StoppedState() }
        }
        return { kind: 'failed', next: new StoppedState(), error: this.settled.error }
    }
}

class StateMachine {
    private state: LifecycleState = new StoppedState()

    async start(ctx: LifecycleContext): Promise<void> {
        await this.drive((s) => s.onStart(ctx))
    }

    async stop(ctx: LifecycleContext): Promise<void> {
        await this.drive((s) => s.onStop(ctx))
    }

    private async drive(action: (state: LifecycleState) => Outcome): Promise<void> {
        while (true) {
            const outcome = action(this.state)
            if (outcome.kind === 'transition') {
                this.state = outcome.next
                continue
            }
            if (outcome.kind === 'wait') {
                await outcome.on
                continue
            }
            if (outcome.kind === 'failed') {
                this.state = outcome.next
                throw outcome.error
            }
            return
        }
    }
}

// ---------------------------------------------------------------------------
// Lifecycle: assembles the pieces.

export class Lifecycle<S extends Record<string, object> = Record<never, object>> {
    private readonly machine = new StateMachine()
    private readonly callers = new CallerSet()
    private readonly servicesProvider: () => S
    private readonly runner: Runner
    private readonly ctx: LifecycleContext

    constructor(
        readonly name: string,
        servicesProvider: () => S,
        runner: Runner
    ) {
        this.servicesProvider = servicesProvider
        this.runner = runner
        this.ctx = {
            runStart: () => this.runner.start(),
            runStop: () => this.runner.stop(),
            callerCount: () => this.callers.size(),
        }
    }

    async start(): Promise<StartedLifecycle<S>> {
        const release = this.callers.register()
        logger.info(`Lifecycle[${this.name}]: start requested (callers=${this.callers.size()})`)
        try {
            await this.machine.start(this.ctx)
        } catch (err) {
            release()
            logger.error(`Lifecycle[${this.name}]: start failed`, { error: err })
            throw err
        }
        logger.info(`Lifecycle[${this.name}]: started`)
        return this.makeHandle(release)
    }

    /**
     * Build a child lifecycle on top of this one. The `configure` callback
     * receives this lifecycle's started services and a fresh builder, and
     * returns the builder with the child's services registered. The returned
     * lifecycle's services are `parent ∪ child`.
     *
     * On `start`: this lifecycle is started (or refcounted onto), then the
     * callback runs with the resolved services and the child is started.
     * On `stop`: the child is stopped, then this lifecycle is released.
     */
    chain<S2 extends Record<string, object>>(
        name: string,
        configure: (parentServices: S, builder: LifecycleBuilder<Record<never, object>>) => LifecycleBuilder<S2>
    ): Lifecycle<S & S2> {
        const runner = new ChainedRunner<S, S2>(this, configure, name)
        return new Lifecycle<S & S2>(name, () => runner.getServices(), runner)
    }

    private makeHandle(release: () => boolean): StartedLifecycle<S> {
        return {
            name: this.name,
            services: this.servicesProvider(),
            stop: async (): Promise<void> => {
                if (!release()) {
                    return
                }
                logger.info(`Lifecycle[${this.name}]: stop requested (callers=${this.callers.size()})`)
                try {
                    await this.machine.stop(this.ctx)
                } catch (err) {
                    logger.error(`Lifecycle[${this.name}]: stop failed`, { error: err })
                    throw err
                }
                logger.info(`Lifecycle[${this.name}]: stopped`)
            },
        }
    }
}

export function newLifecycleBuilder(): LifecycleBuilder<Record<never, object>> {
    return LifecycleBuilder.empty()
}
