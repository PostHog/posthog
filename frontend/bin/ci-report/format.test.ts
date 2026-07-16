import { totalComparison } from './format.mjs'

describe('ci-report formatting', () => {
    it('warns on any growth by default', () => {
        expect(totalComparison(1001, 1000).status).toBe('warn')
    })

    it.each([
        [1019, 'ok'],
        [1020, 'warn'],
        [1021, 'warn'],
        [999, 'ok'],
    ])('sets status for %i bytes with a 2%% warning floor', (bytes: number, expectedStatus: string) => {
        expect(totalComparison(bytes, 1000, { warningThresholdPercent: 2 }).status).toBe(expectedStatus)
    })
})
