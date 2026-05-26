import { logger } from '../../utils/logger'

/**
 * Owns the lifecycle of a single value. `start()` produces the value plus a
 * `stop` callback that tears it down. Anyone holding the value only sees
 * the business interface — the start/stop pair stays with the Manager.
 * This lets the lifecycle plumb dependencies (services, pools, config)
 * through a single container without each entry needing to wear a
 * start/stop hat.
 */
export interface Manager<T> {
    start(): Promise<{ value: T; stop: () => Promise<void> }>
}

type ValueOf<M> = M extends Manager<infer T> ? T : never

/** Internal entry captured at registration time. */
interface RegisteredManager {
    name: string
    manager: Manager<unknown>
}

/**
 * Per-lifecycle accumulator. `register` records a `Manager` for each entry;
 * the corresponding value lands in the container only after the lifecycle
 * starts. Until then, the builder is just a typed recipe.
 */
export class LifecycleBuilder<S extends Record<string, object> = Record<never, object>> {
    private constructor(readonly managers: ReadonlyArray<RegisteredManager>) {}

    static empty(): LifecycleBuilder<Record<never, object>> {
        return new LifecycleBuilder<Record<never, object>>([])
    }

    register<Name extends string, M extends Manager<object>>(
        name: Name & (Name extends keyof S ? never : Name),
        manager: M
    ): LifecycleBuilder<S & Record<Name, ValueOf<M>>> {
        return new LifecycleBuilder<S & Record<Name, ValueOf<M>>>([
            ...this.managers,
            { name, manager: manager as Manager<unknown> },
        ])
    }

    build(name: string): Lifecycle<S> {
        const runner = new ManagerRunner(name, this.managers)
        return new Lifecycle<S>(name, () => runner.getContainer() as S, runner)
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
 * exposed in the lifecycle's container without its `start`/`stop`
 * methods.
 */
export function adaptManagedService<T extends ConsumerManagedService>(svc: T): Manager<Omit<T, 'start' | 'stop'>> {
    return {
        async start() {
            await svc.start()
            return {
                value: svc as Omit<T, 'start' | 'stop'>,
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
    readonly container: S
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
 * container is populated incrementally during start and torn down in
 * reverse on stop.
 */
class ManagerRunner implements Runner {
    private started: Array<{ name: string; value: object; stop: () => Promise<void> }> = []
    private containerCache?: Record<string, object>

    constructor(
        private readonly lifecycleName: string,
        private readonly entries: ReadonlyArray<RegisteredManager>
    ) {}

    async start(): Promise<void> {
        const started: Array<{ name: string; value: object; stop: () => Promise<void> }> = []
        for (const entry of this.entries) {
            logger.info(`Lifecycle[${this.lifecycleName}]: starting ${entry.name}`)
            try {
                const { value, stop } = await entry.manager.start()
                started.push({ name: entry.name, value: value as object, stop })
            } catch (err) {
                logger.error(
                    `Lifecycle[${this.lifecycleName}]: ${entry.name} start failed, rolling back ${started.length} started value(s)`,
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
        this.containerCache = Object.fromEntries(started.map((s) => [s.name, s.value]))
    }

    async stop(): Promise<void> {
        const entries = this.started
        this.started = []
        this.containerCache = undefined
        for (let i = entries.length - 1; i >= 0; i--) {
            logger.info(`Lifecycle[${this.lifecycleName}]: stopping ${entries[i].name}`)
            try {
                await entries[i].stop()
            } catch (err) {
                logger.error(`Lifecycle[${this.lifecycleName}]: ${entries[i].name} stop failed`, { error: err })
                throw err
            }
        }
    }

    getContainer(): Record<string, object> {
        if (!this.containerCache) {
            throw new Error('lifecycle not started')
        }
        return this.containerCache
    }
}

/**
 * Runs a child lifecycle on top of a parent lifecycle. On `start`: start
 * (or refcount onto) the parent, resolve its container, hand it to the
 * configure callback to build a child lifecycle, then start the child.
 * On `stop`: stop the child then release the parent. The parent boot is
 * shared across all chains rooted at it via the parent's own refcount.
 */
class ChainedRunner<SParent extends Record<string, object>, SChild extends Record<string, object>> implements Runner {
    private parentHandle?: StartedLifecycle<SParent>
    private childHandle?: StartedLifecycle<SChild>
    private containerCache?: SParent & SChild

    constructor(
        private readonly parent: Lifecycle<SParent>,
        private readonly configure: (
            parentContainer: SParent,
            builder: LifecycleBuilder<Record<never, object>>
        ) => LifecycleBuilder<SChild>,
        private readonly childName: string
    ) {}

    async start(): Promise<void> {
        logger.info(`Lifecycle[${this.childName}]: acquiring parent ${this.parent.name}`)
        const parentHandle = await this.parent.start()
        try {
            const childLifecycle = this.configure(parentHandle.container, LifecycleBuilder.empty()).build(
                this.childName
            )
            const childHandle = await childLifecycle.start()
            this.parentHandle = parentHandle
            this.childHandle = childHandle
            this.containerCache = { ...parentHandle.container, ...childHandle.container }
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
        this.containerCache = undefined
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

    getContainer(): SParent & SChild {
        if (!this.containerCache) {
            throw new Error(`chained lifecycle "${this.childName}" is not started`)
        }
        return this.containerCache
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
    private readonly containerProvider: () => S
    private readonly runner: Runner
    private readonly ctx: LifecycleContext

    constructor(
        readonly name: string,
        containerProvider: () => S,
        runner: Runner
    ) {
        this.containerProvider = containerProvider
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
     * receives this lifecycle's started container and a fresh builder, and
     * returns the builder with the child's entries registered. The returned
     * lifecycle's container is `parent ∪ child`.
     *
     * On `start`: this lifecycle is started (or refcounted onto), then the
     * callback runs with the resolved container and the child is started.
     * On `stop`: the child is stopped, then this lifecycle is released.
     */
    chain<S2 extends Record<string, object>>(
        name: string,
        configure: (parentContainer: S, builder: LifecycleBuilder<Record<never, object>>) => LifecycleBuilder<S2>
    ): Lifecycle<S & S2> {
        const runner = new ChainedRunner<S, S2>(this, configure, name)
        return new Lifecycle<S & S2>(name, () => runner.getContainer(), runner)
    }

    private makeHandle(release: () => boolean): StartedLifecycle<S> {
        return {
            name: this.name,
            container: this.containerProvider(),
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
