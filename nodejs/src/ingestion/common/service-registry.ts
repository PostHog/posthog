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
 * builder's `services` map (typed without `stop` — see `StrippedService`)
 * and pushes the matching `(start, stop)` pair into the ordered `lifecycle`
 * list. The two views grow in lockstep but stay separate so the public
 * services map never exposes the per-service `stop` method.
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
 * Returned by `Lifecycle.start()`. `services` is the same stripped map the
 * builder accumulated — no per-service `stop` is exposed. The
 * lifecycle-level `stop` is the only path that tears these services down,
 * and it's idempotent on this handle.
 */
export interface StartedLifecycle<S extends Record<string, object>> {
    readonly name: string
    readonly services: S
    readonly stop: () => Promise<void>
}

/**
 * A startable phase: knows about its own services only. Composing lifecycles
 * — passing one phase's services into the next phase's construction — is
 * the caller's job and lives outside this module.
 */
export class Lifecycle<S extends Record<string, object> = Record<never, object>> {
    constructor(
        readonly name: string,
        readonly services: S,
        readonly lifecycle: ReadonlyArray<ServiceLifecycle>
    ) {}

    async start(): Promise<StartedLifecycle<S>> {
        const started: ServiceLifecycle[] = []

        try {
            for (const svc of this.lifecycle) {
                await svc.start()
                started.push(svc)
            }
        } catch (err) {
            // Roll back this lifecycle's started services in reverse so we
            // don't leak resources from a partial start. Then rethrow the
            // original error.
            for (let i = started.length - 1; i >= 0; i--) {
                try {
                    await started[i].stop()
                } catch {
                    // best-effort cleanup; propagate the original start error
                }
            }
            throw err
        }

        let stopped = false
        const stop = async (): Promise<void> => {
            if (stopped) {
                return
            }
            stopped = true
            for (let i = started.length - 1; i >= 0; i--) {
                await started[i].stop()
            }
        }

        return {
            name: this.name,
            services: this.services,
            stop,
        }
    }
}

export function newLifecycleBuilder(): LifecycleBuilder<Record<never, object>> {
    return LifecycleBuilder.empty()
}
