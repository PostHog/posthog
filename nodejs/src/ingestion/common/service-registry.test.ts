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
})
