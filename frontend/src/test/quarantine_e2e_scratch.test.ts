// Throwaway fixture validating the jest quarantine adapter end to end in CI. Never merge.
describe('QuarantineE2E', () => {
    test('always fails', () => {
        expect('e2e deliberate sync failure').toBe('tolerated')
    })

    test('passes normally', () => {
        expect(1 + 1).toBe(2)
    })
})

describe('QuarantineAsync', () => {
    test('always rejects', async () => {
        await Promise.resolve()
        expect('e2e deliberate async failure').toBe('skipped')
    })
})
