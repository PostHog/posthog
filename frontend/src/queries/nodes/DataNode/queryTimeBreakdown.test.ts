import { getQueryTimeBreakdown } from './queryTimeBreakdown'

describe('getQueryTimeBreakdown', () => {
    test.each([
        ['fast server, slow transfer', 40_000, 500, true],
        ['slow server', 40_000, 38_000, false],
        ['short total with most of it in transfer', 2_000, 100, false],
        ['transfer just under the share threshold', 10_000, 2_500, false],
    ])('%s', (_, totalMs, serverMs, isTransferSlow) => {
        expect(getQueryTimeBreakdown(totalMs, serverMs)?.isTransferSlow).toBe(isTransferSlow)
    })

    it('splits the total into server and transfer time', () => {
        expect(getQueryTimeBreakdown(39_400, 500)).toEqual({
            totalMs: 39_400,
            serverMs: 500,
            transferMs: 38_900,
            isTransferSlow: true,
        })
    })

    it('returns null when the server did not report its time', () => {
        expect(getQueryTimeBreakdown(5_000, null)).toBeNull()
    })
})
