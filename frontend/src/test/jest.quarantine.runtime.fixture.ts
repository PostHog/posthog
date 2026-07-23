function currentFixtureTestName(): string | undefined {
    const state = (globalThis as typeof globalThis & { expect: jest.Expect }).expect.getState()
    return typeof state.currentTestName === 'string' ? state.currentTestName : undefined
}

describe('jest quarantine runtime fixture', () => {
    beforeAll(() => {
        if (currentFixtureTestName() === undefined) {
            throw new Error('quarantined beforeAll failure')
        }
    })

    beforeEach(() => {
        if (currentFixtureTestName()?.includes('tolerates beforeEach failure')) {
            throw new Error('quarantined beforeEach failure')
        }
    })

    afterEach(() => {
        if (currentFixtureTestName()?.includes('tolerates afterEach failure')) {
            throw new Error('quarantined afterEach failure')
        }
    })

    test('tolerates body failure', () => {
        throw new Error('quarantined body failure')
    })

    test('tolerates async rejection', async () => {
        throw new Error('quarantined async failure')
    })

    test.each([1])('tolerates each row %s', () => {
        throw new Error('quarantined each row failure')
    })

    test('tolerates beforeEach failure', () => {
        expect(true).toBe(true)
    })

    test('tolerates afterEach failure', () => {
        expect(true).toBe(true)
    })

    test('skips body', () => {
        throw new Error('skipped body should not run')
    })
})
