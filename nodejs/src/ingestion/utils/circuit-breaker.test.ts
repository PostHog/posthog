import { CircuitBreaker } from './circuit-breaker'

jest.mock('~/utils/logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

jest.mock('prom-client', () => {
    const actual = jest.requireActual('prom-client')
    const registry = new actual.Registry()
    return {
        ...actual,
        Counter: class FakeCounter {
            labels() {
                return { inc: jest.fn() }
            }
        },
        Gauge: class FakeGauge {
            labels() {
                return { set: jest.fn() }
            }
        },
        register: registry,
    }
})

const defaultConfig = {
    name: 'test',
    failureThreshold: 3,
    initialBackoffMs: 1,
    maxBackoffMs: 10,
    probeSize: 10,
}

describe('CircuitBreaker', () => {
    it('starts closed', () => {
        const cb = new CircuitBreaker(defaultConfig)
        expect(cb.isOpen()).toBe(false)
        expect(cb.getState()).toBe('closed')
    })

    it('does not open below the failure threshold', () => {
        const cb = new CircuitBreaker(defaultConfig)
        cb.recordFailure()
        cb.recordFailure()
        expect(cb.isOpen()).toBe(false)
    })

    it('opens at the failure threshold', () => {
        const cb = new CircuitBreaker(defaultConfig)
        cb.recordFailure()
        cb.recordFailure()
        cb.recordFailure()
        expect(cb.isOpen()).toBe(true)
    })

    it('closes on success', () => {
        const cb = new CircuitBreaker({ ...defaultConfig, failureThreshold: 1 })
        cb.recordFailure()
        expect(cb.isOpen()).toBe(true)

        cb.recordSuccess()
        expect(cb.isOpen()).toBe(false)
    })

    it('resets failure count on success', () => {
        const cb = new CircuitBreaker(defaultConfig)
        cb.recordFailure()
        cb.recordFailure()
        cb.recordSuccess()

        cb.recordFailure()
        cb.recordFailure()
        expect(cb.isOpen()).toBe(false)
    })

    describe('waitForRecovery', () => {
        it('probes and closes circuit when probe succeeds', async () => {
            const cb = new CircuitBreaker({ ...defaultConfig, failureThreshold: 1 })
            cb.recordFailure()

            const probe = jest.fn().mockResolvedValue(true)
            await cb.waitForRecovery(probe)

            expect(cb.isOpen()).toBe(false)
            expect(probe).toHaveBeenCalledWith(defaultConfig.probeSize)
        })

        it('retries probe with backoff until success', async () => {
            const cb = new CircuitBreaker({ ...defaultConfig, failureThreshold: 1 })
            cb.recordFailure()

            let callCount = 0
            const probe = jest.fn().mockImplementation(() => {
                callCount++
                return Promise.resolve(callCount >= 3)
            })

            await cb.waitForRecovery(probe)

            expect(probe).toHaveBeenCalledTimes(3)
            expect(cb.isOpen()).toBe(false)
        })

        it('passes probeSize to the probe function', async () => {
            const cb = new CircuitBreaker({ ...defaultConfig, failureThreshold: 1, probeSize: 42 })
            cb.recordFailure()

            const probe = jest.fn().mockResolvedValue(true)
            await cb.waitForRecovery(probe)

            expect(probe).toHaveBeenCalledWith(42)
        })
    })
})
