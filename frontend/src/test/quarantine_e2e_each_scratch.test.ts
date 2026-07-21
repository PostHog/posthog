// Throwaway fixture validating the jest quarantine adapter end to end in CI. Never merge.
describe('QuarantineEach', () => {
    test.each([[1], [2]])('each row %i fails', (row) => {
        expect(row).toBe('e2e deliberate each failure')
    })
})
