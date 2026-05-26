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
        return new Lifecycle<S>(name, this.services, this.lifecycle)
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
// Service runner: encapsulates "actually run the registered services".

class ServiceRunner {
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

// ---------------------------------------------------------------------------
// Caller set: refcount with single-shot release callbacks.

/**
 * Sequential-ID refcount. Each `register` mints a new id and returns a
 * release callback that, on first call, removes the caller and returns
 * `true`; subsequent calls are no-ops returning `false`.
 */
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

/** A state's synchronous response to `onStart`/`onStop`:
 *   - `transition`: replace the current state and re-apply the same call.
 *   - `wait`: park on this promise, then re-apply against current state.
 *   - `done`: call complete.
 *   - `failed`: call complete with an error; the driver applies `next` and
 *     throws. */
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

/** Services are coming up. Both start and stop callers park on the in-flight
 * boot, then re-evaluate against the resulting Started (or Stopped on
 * failure) state. */
class StartingState implements LifecycleState {
    private settled: 'pending' | 'ok' | { error: unknown } = 'pending'
    private readonly waitOn: Promise<void>

    constructor(startPromise: Promise<void>) {
        // Always-resolves promise that records the outcome. Drivers can park
        // on `waitOn` without worrying about rejection; the next snapshot
        // surfaces success or failure via `settled`.
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

/** Services are running. Start returns immediately (refcount already taken
 * by the driver). Stop checks whether this was the last caller; if so,
 * teardown begins. */
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

/** Services are coming down. A start arriving here parks on the in-flight
 * teardown and transitions to Stopped regardless of stop success — the
 * caller just wants the slate clear before booting fresh. A stop here also
 * parks; it surfaces an error if teardown failed. */
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

/**
 * Drives the state classes. `start`/`stop` loop until the current state
 * returns `done` or `failed`, applying transitions and parking on `wait`
 * outcomes along the way. Because state methods are synchronous, the
 * transition between observing the state and applying the outcome is
 * atomic — concurrent callers can't slip in and cause duplicate side
 * effects.
 */
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
    private readonly runner: ServiceRunner
    private readonly ctx: LifecycleContext

    constructor(
        readonly name: string,
        readonly services: S,
        lifecycle: ReadonlyArray<ServiceLifecycle>
    ) {
        this.runner = new ServiceRunner(lifecycle)
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

    private makeHandle(release: () => boolean): StartedLifecycle<S> {
        return {
            name: this.name,
            services: this.services,
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
