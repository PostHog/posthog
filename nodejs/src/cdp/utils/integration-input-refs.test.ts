import { IntegrationInputRefsRollout } from './integration-input-refs'

describe('IntegrationInputRefsRollout', () => {
    const flushPromises = () => new Promise((resolve) => setImmediate(resolve))

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const cases: [string, () => Promise<boolean>, boolean][] = [
        ['an enabled flag', () => Promise.resolve(true), true],
        ['a disabled flag', () => Promise.resolve(false), false],
        ['a failed evaluation', () => Promise.reject(new Error('flags unavailable')), false],
    ]

    it.each(cases)(
        'reads the flag without waiting and evaluates it once per minute, given %s',
        async (_name, result, expected) => {
            let now = 1_000_000
            jest.spyOn(Date, 'now').mockImplementation(() => now)
            const evaluate = jest.fn(result)
            const rollout = new IntegrationInputRefsRollout(evaluate)

            expect(rollout.isEnabled()).toBe(false)
            expect(rollout.isEnabled()).toBe(false)
            await flushPromises()
            expect(rollout.isEnabled()).toBe(expected)
            expect(evaluate).toHaveBeenCalledTimes(1)

            now += 60_000
            rollout.isEnabled()
            await flushPromises()
            expect(evaluate).toHaveBeenCalledTimes(2)
        }
    )
})
