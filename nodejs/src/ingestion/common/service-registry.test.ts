import { ConsumerManagedService, newLifecycleBuilder } from './service-registry'

type TrackedService = ConsumerManagedService & { startCalls: number; stopCalls: number }

function makeService(name: string, log: string[]): TrackedService {
    const svc: TrackedService = {
        startCalls: 0,
        stopCalls: 0,
        start: jest.fn((): Promise<void> => {
            svc.startCalls++
            log.push(`start:${name}`)
            return Promise.resolve()
        }),
        stop: jest.fn((): Promise<void> => {
            svc.stopCalls++
            log.push(`stop:${name}`)
            return Promise.resolve()
        }),
    }
    return svc
}

describe('Lifecycle', () => {
    it('starts services in registration order', async () => {
        const log: string[] = []
        const a = makeService('a', log)
        const b = makeService('b', log)

        const lifecycle = newLifecycleBuilder().register('a', a).register('b', b).build('phase')
        const started = await lifecycle.start()

        expect(log).toEqual(['start:a', 'start:b'])
        expect(started.name).toBe('phase')
        expect(started.services).toEqual({ a, b })
    })

    it('types each service without per-service start or stop', async () => {
        const log: string[] = []
        const a = makeService('a', log)

        const lifecycle = newLifecycleBuilder().register('a', a).build('phase')
        const { services } = await lifecycle.start()

        // Compile-time check: neither `start` nor `stop` should exist on the
        // typed view. (The runtime object still has both — this is a typed
        // guard, not a wrapped object.) The `@ts-expect-error` lines will
        // FAIL the build if either method is ever re-exposed in the type.
        // @ts-expect-error -- start is intentionally hidden on the started view
        const _start: unknown = services.a.start
        // @ts-expect-error -- stop is intentionally hidden on the started view
        const _stop: unknown = services.a.stop
        expect(_start).toBe(a.start)
        expect(_stop).toBe(a.stop)
    })

    it('supports manual composition of two lifecycles', async () => {
        const log: string[] = []
        const a = makeService('a', log)
        const b = makeService('b', log)

        const server = newLifecycleBuilder().register('a', a).build('server')
        const { services: serverServices, stop: stopServer } = await server.start()

        // Caller wires the next lifecycle using the prior services' business
        // methods (not start/stop — those aren't exposed).
        expect(serverServices.a).toBeDefined()
        const consumer = newLifecycleBuilder().register('b', b).build('consumer')
        const { stop: stopConsumer } = await consumer.start()

        expect(log).toEqual(['start:a', 'start:b'])

        await stopConsumer()
        await stopServer()
        expect(log).toEqual(['start:a', 'start:b', 'stop:b', 'stop:a'])
    })

    it('stops services in reverse registration order', async () => {
        const log: string[] = []
        const a = makeService('a', log)
        const b = makeService('b', log)
        const c = makeService('c', log)

        const lifecycle = newLifecycleBuilder().register('a', a).register('b', b).register('c', c).build('phase')
        const { stop } = await lifecycle.start()
        await stop()

        expect(log).toEqual(['start:a', 'start:b', 'start:c', 'stop:c', 'stop:b', 'stop:a'])
    })

    it('rolls back already-started services when a later service fails to start', async () => {
        const log: string[] = []
        const a = makeService('a', log)
        const b: ConsumerManagedService = {
            start: jest.fn((): Promise<void> => {
                log.push('start:b')
                return Promise.reject(new Error('b failed'))
            }),
            stop: jest.fn((): Promise<void> => {
                log.push('stop:b')
                return Promise.resolve()
            }),
        }

        const lifecycle = newLifecycleBuilder().register('a', a).register('b', b).build('phase')

        await expect(lifecycle.start()).rejects.toThrow('b failed')
        // Only services that successfully started are rolled back, in reverse.
        expect(log).toEqual(['start:a', 'start:b', 'stop:a'])
    })

    it('makes stop idempotent on a single handle', async () => {
        const log: string[] = []
        const a = makeService('a', log)

        const lifecycle = newLifecycleBuilder().register('a', a).build('phase')
        const { stop } = await lifecycle.start()

        await stop()
        await stop()

        expect(a.stopCalls).toBe(1)
    })

    it('starts services only once across multiple start calls', async () => {
        const log: string[] = []
        const a = makeService('a', log)

        const lifecycle = newLifecycleBuilder().register('a', a).build('phase')
        const h1 = await lifecycle.start()
        const h2 = await lifecycle.start()

        expect(a.startCalls).toBe(1)
        expect(h1.services).toBe(h2.services)
    })

    it('keeps services running until the last caller releases', async () => {
        const log: string[] = []
        const a = makeService('a', log)

        const lifecycle = newLifecycleBuilder().register('a', a).build('phase')
        const h1 = await lifecycle.start()
        const h2 = await lifecycle.start()

        await h1.stop()
        expect(a.stopCalls).toBe(0)

        await h2.stop()
        expect(a.stopCalls).toBe(1)
        expect(log).toEqual(['start:a', 'stop:a'])
    })

    it('restarts cleanly after a full stop', async () => {
        const log: string[] = []
        const a = makeService('a', log)

        const lifecycle = newLifecycleBuilder().register('a', a).build('phase')
        const h1 = await lifecycle.start()
        await h1.stop()

        const h2 = await lifecycle.start()
        await h2.stop()

        expect(a.startCalls).toBe(2)
        expect(a.stopCalls).toBe(2)
        expect(log).toEqual(['start:a', 'stop:a', 'start:a', 'stop:a'])
    })

    it('shares the same start operation across concurrent start calls', async () => {
        const log: string[] = []
        let resolveStart: (() => void) | undefined
        const a: ConsumerManagedService = {
            start: jest.fn((): Promise<void> => {
                log.push('start:a:begin')
                return new Promise<void>((resolve) => {
                    resolveStart = () => {
                        log.push('start:a:end')
                        resolve()
                    }
                })
            }),
            stop: jest.fn((): Promise<void> => {
                log.push('stop:a')
                return Promise.resolve()
            }),
        }

        const lifecycle = newLifecycleBuilder().register('a', a).build('phase')

        const p1 = lifecycle.start()
        const p2 = lifecycle.start()

        // Both starts are pending against the same in-flight boot — start:a
        // has been called exactly once.
        await new Promise((resolve) => setImmediate(resolve))
        expect(log).toEqual(['start:a:begin'])
        expect(a.start).toHaveBeenCalledTimes(1)

        resolveStart!()
        const [h1, h2] = await Promise.all([p1, p2])

        await h1.stop()
        expect(a.stop).toHaveBeenCalledTimes(0)
        await h2.stop()
        expect(a.stop).toHaveBeenCalledTimes(1)
    })

    it('waits for in-flight stop before starting fresh', async () => {
        const log: string[] = []
        let startCalls = 0
        let stopCalls = 0
        let resolveFirstStop: (() => void) | undefined
        const a: ConsumerManagedService = {
            start: jest.fn((): Promise<void> => {
                startCalls++
                log.push('start:a')
                return Promise.resolve()
            }),
            stop: jest.fn((): Promise<void> => {
                stopCalls++
                // Only the first stop blocks; subsequent stops resolve
                // immediately so the test can clean up without hanging.
                if (stopCalls === 1) {
                    log.push('stop:a:begin')
                    return new Promise<void>((resolve) => {
                        resolveFirstStop = () => {
                            log.push('stop:a:end')
                            resolve()
                        }
                    })
                }
                log.push('stop:a')
                return Promise.resolve()
            }),
        }

        const lifecycle = newLifecycleBuilder().register('a', a).build('phase')
        const h1 = await lifecycle.start()
        const stopPromise = h1.stop()

        // While stop is in flight, kick off a new start. It should wait for
        // the stop to finish before bringing the services back up.
        const restart = lifecycle.start()
        await new Promise((resolve) => setImmediate(resolve))
        expect(log).toEqual(['start:a', 'stop:a:begin'])

        resolveFirstStop!()
        await stopPromise
        const h2 = await restart

        expect(log).toEqual(['start:a', 'stop:a:begin', 'stop:a:end', 'start:a'])

        await h2.stop()
        expect(startCalls).toBe(2)
        expect(stopCalls).toBe(2)
    })
})
