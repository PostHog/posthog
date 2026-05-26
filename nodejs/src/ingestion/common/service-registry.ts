/**
 * Lifecycle contract honored by every registered service: start before the
 * dependents that use it, stop after the dependents that use it. No-op
 * implementations are encouraged for services with nothing real to do at
 * those boundaries — explicit beats silent skipping.
 */
export interface ConsumerManagedService {
    start(): Promise<void>
    stop(): Promise<void>
}

/** Bound (start, stop) pair captured at registration time. Used internally to
 * sequence service startup and shutdown without re-exposing the underlying
 * service objects. */
interface ServiceLifecycle {
    start: () => Promise<void>
    stop: () => Promise<void>
}

/**
 * Per-lifecycle accumulator. Each `register` stores the service in the
 * builder's `services` map (typed without `start`/`stop`) and pushes the
 * matching `(start, stop)` pair into the ordered `lifecycle` list. The two
 * views grow in lockstep but stay separate so the public services map never
 * exposes per-service start/stop.
 */
export class LifecycleBuilder<S extends Record<string, object> = Record<never, object>> {
    private constructor(
        readonly services: S,
        readonly lifecycle: ReadonlyArray<ServiceLifecycle>
    ) {}

    static empty(): LifecycleBuilder<Record<never, object>> {
        return new LifecycleBuilder<Record<never, object>>({}, [])
    }

    register<Name extends string, T extends ConsumerManagedService>(
        name: Name & (Name extends keyof S ? never : Name),
        service: T
    ): LifecycleBuilder<S & Record<Name, Omit<T, 'start' | 'stop'>>> {
        return new LifecycleBuilder<S & Record<Name, Omit<T, 'start' | 'stop'>>>(
            { ...this.services, [name]: service },
            [...this.lifecycle, { start: () => service.start(), stop: () => service.stop() }]
        )
    }

    build(name: string): Lifecycle<S> {
        const services = this.services
        const runner = new ServiceRunner(this.lifecycle)
        return new Lifecycle<S>(name, () => services, runner)
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
 * Boots and tears down the ordered list of services. Tracks which services
 * successfully started so `stop` only tears those down.
 */
class ServiceRunner implements Runner {
    private started: ServiceLifecycle[] = []

    constructor(private readonly services: ReadonlyArray<ServiceLifecycle>) {}

    async start(): Promise<void> {
        const started: ServiceLifecycle[] = []
        try {
            for (const svc of this.services) {
                await svc.start()
                started.push(svc)
            }
            this.started = started
        } catch (err) {
            // Roll back successfully-started services in reverse so we don't
            // leak resources from a partial start; then rethrow.
            for (let i = started.length - 1; i >= 0; i--) {
                try {
                    await started[i].stop()
                } catch {
                    // best-effort cleanup; propagate the original start error
                }
            }
            throw err
        }
    }

    async stop(): Promise<void> {
        const svcs = this.started
        this.started = []
        for (let i = svcs.length - 1; i >= 0; i--) {
            await svcs[i].stop()
        }
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

    constructor(
        private readonly parent: Lifecycle<SParent>,
        private readonly configure: (
            parentServices: SParent,
            builder: LifecycleBuilder<Record<never, object>>
        ) => LifecycleBuilder<SChild>,
        private readonly childName: string
    ) {}

    async start(): Promise<void> {
        const parentHandle = await this.parent.start()
        try {
            const childLifecycle = this.configure(parentHandle.services, LifecycleBuilder.empty()).build(this.childName)
            this.childHandle = await childLifecycle.start()
            this.parentHandle = parentHandle
        } catch (err) {
            // Child construction or start failed; release the parent reference
            // we just acquired so we don't leak it.
            try {
                await parentHandle.stop()
            } catch {
                // best-effort; propagate the original child error
            }
            throw err
        }
    }

    async stop(): Promise<void> {
        const childHandle = this.childHandle
        const parentHandle = this.parentHandle
        this.childHandle = undefined
        this.parentHandle = undefined
        try {
            if (childHandle) {
                await childHandle.stop()
            }
        } finally {
            if (parentHandle) {
                await parentHandle.stop()
            }
        }
    }

    getServices(): SParent & SChild {
        if (!this.parentHandle || !this.childHandle) {
            throw new Error(`chained lifecycle "${this.childName}" is not started`)
        }
        return { ...this.parentHandle.services, ...this.childHandle.services }
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
        try {
            await this.machine.start(this.ctx)
        } catch (err) {
            release()
            throw err
        }
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
                await this.machine.stop(this.ctx)
            },
        }
    }
}

export function newLifecycleBuilder(): LifecycleBuilder<Record<never, object>> {
    return LifecycleBuilder.empty()
}
