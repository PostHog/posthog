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

/** Maps each container key to the `Manager` that produces its value. */
type ManagerMap<S> = { [K in keyof S]: Manager<S[K]> }

/**
 * Per-scope accumulator. `add` records a `Manager` for each entry;
 * the corresponding value lands in the container only after the scope
 * starts. Until then, the builder is just a typed recipe.
 */
export class ScopeBuilder<S extends Record<string, object> = Record<never, object>> {
    private constructor(private readonly managers: ManagerMap<S>) {}

    static empty(): ScopeBuilder<Record<never, object>> {
        return new ScopeBuilder<Record<never, object>>({})
    }

    add<Name extends string, M extends Manager<object>>(
        name: Name & (Name extends keyof S ? never : Name),
        manager: M
    ): ScopeBuilder<S & Record<Name, ValueOf<M>>> {
        // Adding the `name` key with its `manager` produces exactly
        // `ManagerMap<S & Record<Name, ValueOf<M>>>`, but a computed-key
        // spread only types as a string index signature, so assert the shape
        // the method signature already guarantees.
        const managers: Record<string, Manager<object>> = { ...this.managers, [name]: manager }
        return new ScopeBuilder<S & Record<Name, ValueOf<M>>>(managers as ManagerMap<S & Record<Name, ValueOf<M>>>)
    }

    build(name: string): Scope<S> {
        const runner = new ManagerRunner<S>(name, this.managers)
        return new Scope<S>(name, () => runner.getContainer(), runner)
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
 * Boots and tears down the map of managers. They start in parallel, so
 * order is irrelevant; `stop` tears down only the ones that started.
 */
class ManagerRunner<S extends Record<string, object>> implements Runner {
    private started: Array<{ name: string; value: object; stop: () => Promise<void> }> = []
    private containerCache?: S

    constructor(
        private readonly scopeName: string,
        private readonly managers: ManagerMap<S>
    ) {}

    async start(): Promise<void> {
        const entries: Array<[string, Manager<object>]> = Object.entries(this.managers)
        logger.info(`Scope[${this.scopeName}]: starting ${entries.length} entries in parallel`)

        const results = await Promise.allSettled(
            entries.map(async ([name, manager]) => {
                logger.info(`Scope[${this.scopeName}]: starting ${name}`)
                return await manager.start()
            })
        )

        const started: Array<{ name: string; value: object; stop: () => Promise<void> }> = []
        const failures: Array<{ name: string; error: unknown }> = []

        for (let i = 0; i < results.length; i++) {
            const result = results[i]
            const name = entries[i][0]
            if (result.status === 'fulfilled') {
                started.push({ name, value: result.value.value, stop: result.value.stop })
            } else {
                failures.push({ name, error: result.reason })
            }
        }

        if (failures.length > 0) {
            for (const f of failures) {
                logger.error(`Scope[${this.scopeName}]: ${f.name} start failed`, { error: f.error })
            }
            logger.error(`Scope[${this.scopeName}]: start failed, rolling back ${started.length} started value(s)`)
            for (let i = started.length - 1; i >= 0; i--) {
                try {
                    await started[i].stop()
                } catch (rollbackErr) {
                    logger.error(`Scope[${this.scopeName}]: ${started[i].name} stop failed during rollback`, {
                        error: rollbackErr,
                    })
                }
            }
            throw failures[0].error
        }

        this.started = started
        // `managers` is typed `ManagerMap<S>`, so each entry's value is the
        // `S[K]` for its key — the assembled record is therefore `S`. The
        // assertion only bridges `Object.fromEntries` erasing per-key types.
        this.containerCache = Object.fromEntries(started.map((s) => [s.name, s.value])) as S
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

    getContainer(): S {
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
 * shared across all extensions rooted at it via the parent's own refcount.
 */
class ExtendedRunner<SParent extends Record<string, object>, SChild extends Record<string, object>> implements Runner {
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
            logger.error(`Scope[${this.childName}]: extend start failed, releasing parent ${this.parent.name}`, {
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
            throw new Error(`extended scope "${this.childName}" is not started`)
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
    extend<S2 extends Record<string, object>>(
        name: string,
        configure: (parentContainer: S, builder: ScopeBuilder<Record<never, object>>) => ScopeBuilder<S2>
    ): Scope<S & S2> {
        const runner = new ExtendedRunner<S, S2>(this, configure, name)
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

/**
 * Builds a root scope with the given name. The `configure` callback
 * receives an empty builder and returns the builder with the scope's
 * entries registered. Mirrors `Scope.extend` so root and child scopes
 * have the same construction shape.
 */
export function newScope<S extends Record<string, object>>(
    name: string,
    configure: (builder: ScopeBuilder<Record<never, object>>) => ScopeBuilder<S>
): Scope<S> {
    return configure(ScopeBuilder.empty()).build(name)
}
