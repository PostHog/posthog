// Throwaway fixture validating the jest quarantine adapter end to end in CI. Never merge.
test('quarantine e2e scratch always fails', () => {
    expect('e2e deliberate nodejs failure').toBe('tolerated')
})
