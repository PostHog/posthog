import { logger } from '../../utils/logger'

/**
 * Owns the scope of a single value. `start()` produces the value plus a
 * `stop` callback that tears it down. Anyone holding the value only sees
 * the business interface — the start/stop pair stays with the Manager.
 * This lets the scope plumb dependencies (services, pools, config)
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
 * Per-scope accumulator. `register` records a `Manager` for each entry;
 * the corresponding value lands in the container only after the scope
 * starts. Until then, the builder is just a typed recipe.
 */
export class ScopeBuilder<S extends Record<string, object> = Record<never, object>> {
    private constructor(readonly managers: ReadonlyArray<RegisteredManager>) {}

    static empty(): ScopeBuilder<Record<never, object>> {
        return new ScopeBuilder<Record<never, object>>([])
    }

    register<Name extends string, M extends Manager<object>>(
        name: Name & (Name extends keyof S ? never : Name),
        manager: M
    ): ScopeBuilder<S & Record<Name, ValueOf<M>>> {
        return new ScopeBuilder<S & Record<Name, ValueOf<M>>>([
            ...this.managers,
            { name, manager: manager as Manager<unknown> },
        ])
    }

    build(name: string): Scope<S> {
        const runner = new ManagerRunner(name, this.managers)
        return new Scope<S>(name, () => runner.getContainer() as S, runner)
    }
}

/**
 * Legacy service shape — exposes `start()/stop()` directly on the
 * business object. Prefer the `Manager<T>` shape for new code; this is
 * kept for adapter use so existing services can be wired into a scope
 * without refactoring their interface.
 */
export interface ConsumerManagedService {
    start(): Promise<void>
    stop(): Promise<void>
}

/**
 * Adapts a legacy service to the `Manager` shape. The adapted service is
 * exposed in the scope's container without its `start`/`stop`
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
 * Returned by `Scope.start()`. The handle's `stop` removes this caller
 * from the refcount and is single-shot — calling it twice has no effect
 * after the first call.
 */
export interface StartedScope<S extends Record<string, object>> {
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
        private readonly scopeName: string,
        private readonly entries: ReadonlyArray<RegisteredManager>
    ) {}

    async start(): Promise<void> {
        const started: Array<{ name: string; value: object; stop: () => Promise<void> }> = []
        for (const entry of this.entries) {
            logger.info(`Scope[${this.scopeName}]: starting ${entry.name}`)
            try {
                const { value, stop } = await entry.manager.start()
                started.push({ name: entry.name, value: value as object, stop })
            } catch (err) {
                logger.error(
                    `Scope[${this.scopeName}]: ${entry.name} start failed, rolling back ${started.length} started value(s)`,
                    { error: err }
                )
                for (let i = started.length - 1; i >= 0; i--) {
                    try {
                        await started[i].stop()
                    } catch (rollbackErr) {
                        logger.error(`Scope[${this.scopeName}]: ${started[i].name} stop failed during rollback`, {
                            error: rollbackErr,
                        })
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
            logger.info(`Scope[${this.scopeName}]: stopping ${entries[i].name}`)
            try {
                await entries[i].stop()
            } catch (err) {
                logger.error(`Scope[${this.scopeName}]: ${entries[i].name} stop failed`, { error: err })
                throw err
            }
        }
    }

    getContainer(): Record<string, object> {
        if (!this.containerCache) {
            throw new Error('scope not started')
        }
        return this.containerCache
    }
}

/**
 * Runs a child scope on top of a parent scope. On `start`: start
 * (or refcount onto) the parent, resolve its container, hand it to the
 * configure callback to build a child scope, then start the child.
 * On `stop`: stop the child then release the parent. The parent boot is
 * shared across all nests rooted at it via the parent's own refcount.
 */
class NestedRunner<SParent extends Record<string, object>, SChild extends Record<string, object>> implements Runner {
    private parentHandle?: StartedScope<SParent>
    private childHandle?: StartedScope<SChild>
    private containerCache?: SParent & SChild

    constructor(
        private readonly parent: Scope<SParent>,
        private readonly configure: (
            parentContainer: SParent,
            builder: ScopeBuilder<Record<never, object>>
        ) => ScopeBuilder<SChild>,
        private readonly childName: string
    ) {}

    async start(): Promise<void> {
        logger.info(`Scope[${this.childName}]: acquiring parent ${this.parent.name}`)
        const parentHandle = await this.parent.start()
        try {
            const childScope = this.configure(parentHandle.container, ScopeBuilder.empty()).build(this.childName)
            const childHandle = await childScope.start()
            this.parentHandle = parentHandle
            this.childHandle = childHandle
            this.containerCache = { ...parentHandle.container, ...childHandle.container }
        } catch (err) {
            logger.error(`Scope[${this.childName}]: nest start failed, releasing parent ${this.parent.name}`, {
                error: err,
            })
            try {
                await parentHandle.stop()
            } catch (parentStopErr) {
                logger.error(`Scope[${this.childName}]: parent ${this.parent.name} stop failed during rollback`, {
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
                logger.info(`Scope[${this.childName}]: releasing parent ${this.parent.name}`)
                await parentHandle.stop()
            }
        }
    }

    getContainer(): SParent & SChild {
        if (!this.containerCache) {
            throw new Error(`nested scope "${this.childName}" is not started`)
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

interface ScopeContext {
    runStart(): Promise<void>
    runStop(): Promise<void>
    callerCount(): number
}

type Outcome =
    | { kind: 'transition'; next: ScopeState }
    | { kind: 'wait'; on: Promise<unknown> }
    | { kind: 'done' }
    | { kind: 'failed'; next: ScopeState; error: unknown }

interface ScopeState {
    onStart(ctx: ScopeContext): Outcome
    onStop(ctx: ScopeContext): Outcome
}

class StoppedState implements ScopeState {
    onStart(ctx: ScopeContext): Outcome {
        return { kind: 'transition', next: new StartingState(ctx.runStart()) }
    }
    onStop(_ctx: ScopeContext): Outcome {
        return { kind: 'done' }
    }
}

class StartingState implements ScopeState {
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

    onStart(_ctx: ScopeContext): Outcome {
        return this.snapshot()
    }
    onStop(_ctx: ScopeContext): Outcome {
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

class StartedState implements ScopeState {
    onStart(_ctx: ScopeContext): Outcome {
        return { kind: 'done' }
    }
    onStop(ctx: ScopeContext): Outcome {
        if (ctx.callerCount() === 0) {
            return { kind: 'transition', next: new StoppingState(ctx.runStop()) }
        }
        return { kind: 'done' }
    }
}

class StoppingState implements ScopeState {
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

    onStart(_ctx: ScopeContext): Outcome {
        if (this.settled === 'pending') {
            return { kind: 'wait', on: this.waitOn }
        }
        return { kind: 'transition', next: new StoppedState() }
    }

    onStop(_ctx: ScopeContext): Outcome {
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
    private state: ScopeState = new StoppedState()

    async start(ctx: ScopeContext): Promise<void> {
        await this.drive((s) => s.onStart(ctx))
    }

    async stop(ctx: ScopeContext): Promise<void> {
        await this.drive((s) => s.onStop(ctx))
    }

    private async drive(action: (state: ScopeState) => Outcome): Promise<void> {
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
// Scope: assembles the pieces.

export class Scope<S extends Record<string, object> = Record<never, object>> {
    private readonly machine = new StateMachine()
    private readonly callers = new CallerSet()
    private readonly containerProvider: () => S
    private readonly runner: Runner
    private readonly ctx: ScopeContext

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

    async start(): Promise<StartedScope<S>> {
        const release = this.callers.register()
        logger.info(`Scope[${this.name}]: start requested (callers=${this.callers.size()})`)
        try {
            await this.machine.start(this.ctx)
        } catch (err) {
            release()
            logger.error(`Scope[${this.name}]: start failed`, { error: err })
            throw err
        }
        logger.info(`Scope[${this.name}]: started`)
        return this.makeHandle(release)
    }

    /**
     * Build a child scope on top of this one. The `configure` callback
     * receives this scope's started container and a fresh builder, and
     * returns the builder with the child's entries registered. The returned
     * scope's container is `parent ∪ child`.
     *
     * On `start`: this scope is started (or refcounted onto), then the
     * callback runs with the resolved container and the child is started.
     * On `stop`: the child is stopped, then this scope is released.
     */
    nest<S2 extends Record<string, object>>(
        name: string,
        configure: (parentContainer: S, builder: ScopeBuilder<Record<never, object>>) => ScopeBuilder<S2>
    ): Scope<S & S2> {
        const runner = new NestedRunner<S, S2>(this, configure, name)
        return new Scope<S & S2>(name, () => runner.getContainer(), runner)
    }

    private makeHandle(release: () => boolean): StartedScope<S> {
        return {
            name: this.name,
            container: this.containerProvider(),
            stop: async (): Promise<void> => {
                if (!release()) {
                    return
                }
                logger.info(`Scope[${this.name}]: stop requested (callers=${this.callers.size()})`)
                try {
                    await this.machine.stop(this.ctx)
                } catch (err) {
                    logger.error(`Scope[${this.name}]: stop failed`, { error: err })
                    throw err
                }
                logger.info(`Scope[${this.name}]: stopped`)
            },
        }
    }
}

export function newScopeBuilder(): ScopeBuilder<Record<never, object>> {
    return ScopeBuilder.empty()
}
