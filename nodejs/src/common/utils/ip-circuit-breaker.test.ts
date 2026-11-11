import { IpCircuitBreaker } from './ip-circuit-breaker'

const options = { minFailures: 3, failureRatio: 0.5, windowMs: 10_000, cooldownMs: 30_000 }

describe('IpCircuitBreaker', () => {
    let breaker: IpCircuitBreaker

    beforeEach(() => {
        jest.useFakeTimers({ now: new Date('2026-01-01T00:00:00Z') })
        breaker = new IpCircuitBreaker(options)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    function recordMany(addresses: string[], outcomes: boolean[]): void {
        for (const failed of outcomes) {
            breaker.record(addresses, failed)
        }
    }

    test.each([
        ['opens after enough failures at a high ratio', [true, true, true], true],
        ['stays closed after too few failures', [true, true], false],
        ['stays closed at a low failure ratio', [true, false, false, true, false, false, true, false], false],
    ])('%s', (_name, outcomes, opens) => {
        recordMany(['1.1.1.1'], outcomes)

        expect(breaker.check(['1.1.1.1'])).toEqual(opens ? { address: '1.1.1.1', retryInMs: 30_000 } : null)
    })

    it('does not count failures from an earlier window', () => {
        recordMany(['1.1.1.1'], [true, true])
        jest.advanceTimersByTime(10_000)
        recordMany(['1.1.1.1'], [true])

        expect(breaker.check(['1.1.1.1'])).toBeNull()
    })

    it('rejects a hostname only when every address it resolves to is open', () => {
        recordMany(['1.1.1.1', '2.2.2.2'], [true, true, true])
        recordMany(['3.3.3.3'], [true, true, true])

        expect(breaker.check(['2.2.2.2', '1.1.1.1'])).toMatchObject({ address: '2.2.2.2' })
        expect(breaker.check(['1.1.1.1', '4.4.4.4'])).toBeNull()
    })

    test.each([
        ['closes after a success', false, null],
        ['opens again after one failure', true, { address: '1.1.1.1', retryInMs: 30_000 }],
    ])('when the pause ends, %s', (_name, failed, expected) => {
        recordMany(['1.1.1.1'], [true, true, true])
        jest.advanceTimersByTime(30_000)

        expect(breaker.check(['1.1.1.1'])).toBeNull()
        breaker.record(['1.1.1.1'], failed)
        expect(breaker.check(['1.1.1.1'])).toEqual(expected)
    })

    it('ignores outcomes of requests that started before the address opened', () => {
        recordMany(['1.1.1.1'], [true, true, true])
        jest.advanceTimersByTime(1_000)
        recordMany(['1.1.1.1'], [false, false])

        expect(breaker.check(['1.1.1.1'])).toEqual({ address: '1.1.1.1', retryInMs: 29_000 })
    })
})
