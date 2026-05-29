import { Manager, newScope } from './service-registry'

type TrackedManager = Manager<{ name: string }> & { startCalls: number; stopCalls: number }

function makeManager(name: string, log: string[]): TrackedManager {
    const manager: TrackedManager = {
        startCalls: 0,
        stopCalls: 0,
        start: jest.fn(() => {
            manager.startCalls++
            log.push(`start:${name}`)
            return Promise.resolve({
                value: { name },
                stop: (): Promise<void> => {
                    manager.stopCalls++
                    log.push(`stop:${name}`)
                    return Promise.resolve()
                },
            })
        }),
    }
    return manager
}

describe('Lifecycle', () => {
    it('starts services in registration order', async () => {
        const log: string[] = []
        const a = makeManager('a', log)
        const b = makeManager('b', log)

        const lifecycle = newScope('phase', (builder) => builder.add('a', a).add('b', b))
        const started = await lifecycle.start()

        expect(log).toEqual(['start:a', 'start:b'])
        expect(started.name).toBe('phase')
        expect(started.container).toEqual({ a: { name: 'a' }, b: { name: 'b' } })

        await started.stop()
    })

    it('supports manual composition of two lifecycles', async () => {
        const log: string[] = []
        const a = makeManager('a', log)
        const b = makeManager('b', log)

        const server = newScope('server', (builder) => builder.add('a', a))
        const { container: serverContainer, stop: stopServer } = await server.start()

        // Caller wires the next lifecycle using the prior container's business
        // value.
        expect(serverContainer.a).toEqual({ name: 'a' })
        const consumer = newScope('consumer', (builder) => builder.add('b', b))
        const { stop: stopConsumer } = await consumer.start()

        expect(log).toEqual(['start:a', 'start:b'])

        await stopConsumer()
        await stopServer()
        expect(log).toEqual(['start:a', 'start:b', 'stop:b', 'stop:a'])
    })

    it('stops services in reverse registration order', async () => {
        const log: string[] = []
        const a = makeManager('a', log)
        const b = makeManager('b', log)
        const c = makeManager('c', log)

        const lifecycle = newScope('phase', (builder) => builder.add('a', a).add('b', b).add('c', c))
        const { stop } = await lifecycle.start()
        await stop()

        expect(log).toEqual(['start:a', 'start:b', 'start:c', 'stop:c', 'stop:b', 'stop:a'])
    })

    it('rolls back already-started services when a later service fails to start', async () => {
        const log: string[] = []
        const a = makeManager('a', log)
        const b: Manager<{ name: string }> = {
            start: jest.fn(() => {
                log.push('start:b')
                return Promise.reject(new Error('b failed'))
            }),
        }

        const lifecycle = newScope('phase', (builder) => builder.add('a', a).add('b', b))

        await expect(lifecycle.start()).rejects.toThrow('b failed')
        // Only services that successfully started are rolled back, in reverse.
        expect(log).toEqual(['start:a', 'start:b', 'stop:a'])
    })

    it('makes stop idempotent on a single handle', async () => {
        const log: string[] = []
        const a = makeManager('a', log)

        const lifecycle = newScope('phase', (builder) => builder.add('a', a))
        const { stop } = await lifecycle.start()

        await stop()
        await stop()

        expect(a.stopCalls).toBe(1)
    })

    it('starts services only once across multiple start calls', async () => {
        const log: string[] = []
        const a = makeManager('a', log)

        const lifecycle = newScope('phase', (builder) => builder.add('a', a))
        const h1 = await lifecycle.start()
        const h2 = await lifecycle.start()

        expect(a.startCalls).toBe(1)
        expect(h1.container).toBe(h2.container)

        await h1.stop()
        await h2.stop()
    })

    it('keeps services running until the last caller releases', async () => {
        const log: string[] = []
        const a = makeManager('a', log)

        const lifecycle = newScope('phase', (builder) => builder.add('a', a))
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
        const a = makeManager('a', log)

        const lifecycle = newScope('phase', (builder) => builder.add('a', a))
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
        const stopA = jest.fn((): Promise<void> => {
            log.push('stop:a')
            return Promise.resolve()
        })
        const a: Manager<{ name: string }> = {
            start: jest.fn(() => {
                log.push('start:a:begin')
                return new Promise<{ value: { name: string }; stop: () => Promise<void> }>((resolve) => {
                    resolveStart = () => {
                        log.push('start:a:end')
                        resolve({ value: { name: 'a' }, stop: stopA })
                    }
                })
            }),
        }

        const lifecycle = newScope('phase', (builder) => builder.add('a', a))

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
        expect(stopA).toHaveBeenCalledTimes(0)
        await h2.stop()
        expect(stopA).toHaveBeenCalledTimes(1)
    })

    it('waits for in-flight stop before starting fresh', async () => {
        const log: string[] = []
        let startCalls = 0
        let stopCalls = 0
        let resolveFirstStop: (() => void) | undefined
        const a: Manager<{ name: string }> = {
            start: jest.fn(() => {
                startCalls++
                log.push('start:a')
                return Promise.resolve({
                    value: { name: 'a' },
                    stop: (): Promise<void> => {
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
                    },
                })
            }),
        }

        const lifecycle = newScope('phase', (builder) => builder.add('a', a))
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

    it('extends a parent scope with a child scope', async () => {
        const log: string[] = []
        const a = makeManager('a', log)
        const b = makeManager('b', log)

        const parent = newScope('parent', (builder) => builder.add('a', a))
        const child = parent.extend('child', (services, builder) => {
            // Services from the parent must be available here.
            expect(services.a).toEqual({ name: 'a' })
            return builder.add('b', b)
        })

        const started = await child.start()

        expect(log).toEqual(['start:a', 'start:b'])
        expect(started.name).toBe('child')
        expect(started.container).toEqual({ a: { name: 'a' }, b: { name: 'b' } })

        await started.stop()
        // Child first, then parent.
        expect(log).toEqual(['start:a', 'start:b', 'stop:b', 'stop:a'])
    })

    it('refcounts the parent across multiple extensions', async () => {
        const log: string[] = []
        const a = makeManager('a', log)
        const b = makeManager('b', log)
        const c = makeManager('c', log)

        const parent = newScope('parent', (builder) => builder.add('a', a))
        const childB = parent.extend('childB', (_services, builder) => builder.add('b', b))
        const childC = parent.extend('childC', (_services, builder) => builder.add('c', c))

        const hB = await childB.start()
        const hC = await childC.start()

        // Parent boots exactly once even though both extensions started.
        expect(a.startCalls).toBe(1)
        expect(b.startCalls).toBe(1)
        expect(c.startCalls).toBe(1)

        await hB.stop()
        // Releasing one extension doesn't tear the parent down — the other
        // extension still holds it.
        expect(a.stopCalls).toBe(0)
        expect(b.stopCalls).toBe(1)

        await hC.stop()
        // Last extension released; parent now stops.
        expect(a.stopCalls).toBe(1)
        expect(c.stopCalls).toBe(1)
    })

    it('rolls back the parent when the child fails to start', async () => {
        const log: string[] = []
        const a = makeManager('a', log)
        const failing: Manager<{ name: string }> = {
            start: jest.fn(() => Promise.reject(new Error('child boom'))),
        }

        const parent = newScope('parent', (builder) => builder.add('a', a))
        const child = parent.extend('child', (_services, builder) => builder.add('bad', failing))

        await expect(child.start()).rejects.toThrow('child boom')

        // Parent was started, then released when the child failed.
        expect(a.startCalls).toBe(1)
        expect(a.stopCalls).toBe(1)
    })

    it('reconstructs the child on each restart', async () => {
        const log: string[] = []
        const a = makeManager('a', log)
        let buildCalls = 0

        const parent = newScope('parent', (builder) => builder.add('a', a))
        const child = parent.extend('child', (_services, builder) => {
            buildCalls++
            const b = makeManager(`b${buildCalls}`, log)
            return builder.add('b', b)
        })

        const h1 = await child.start()
        await h1.stop()

        const h2 = await child.start()
        await h2.stop()

        expect(buildCalls).toBe(2)
        expect(a.startCalls).toBe(2)
        expect(a.stopCalls).toBe(2)
        expect(log).toEqual(['start:a', 'start:b1', 'stop:b1', 'stop:a', 'start:a', 'start:b2', 'stop:b2', 'stop:a'])
    })
})
