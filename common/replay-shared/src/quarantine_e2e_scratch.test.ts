// Throwaway fixture validating the jest quarantine adapter end to end in CI. Never merge.
describe('QuarantineReplayShared', () => {
    test('always fails', () => {
        expect('e2e deliberate replay-shared failure').toBe('tolerated')
    })
})
