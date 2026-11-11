import { ConnectionRateLimiter } from './connection-rate-limiter'

describe('ConnectionRateLimiter', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: new Date('2026-01-01T00:00:00Z') })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('allows a burst per address, then refills at the configured rate', () => {
        const limiter = new ConnectionRateLimiter({ perSecond: 2, burst: 3 })
        const take = (address: string, count: number): boolean[] =>
            Array.from({ length: count }, () => limiter.tryTake(address))

        expect(take('1.1.1.1', 4)).toEqual([true, true, true, false])
        expect(take('2.2.2.2', 1)).toEqual([true])

        jest.advanceTimersByTime(1_000)
        expect(take('1.1.1.1', 3)).toEqual([true, true, false])

        jest.advanceTimersByTime(60_000)
        expect(take('1.1.1.1', 4)).toEqual([true, true, true, false])
    })
})
