import { ApiRequestTiming } from 'lib/apiRequestTiming'

import { getQueryTimeBreakdown, getSingleRequestServerMs } from './queryTimeBreakdown'

describe('query time breakdown', () => {
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

    const timing = (overrides: Partial<ApiRequestTiming> = {}): ApiRequestTiming => ({
        request_total_ms: 39_000,
        envoy_upstream_ms: 500,
        resource_timing_status: 'matched',
        fetch_attempts: 1,
        ...overrides,
    })

    test.each([
        ['one request covering the load', [timing()], 500],
        ['no upstream time reported', [timing({ envoy_upstream_ms: undefined })], null],
        ['an async submit followed by polling', [timing({ request_total_ms: 200 })], null],
        ['an authentication retry', [timing({ fetch_attempts: 2 })], null],
        ['several submit requests', [timing(), timing()], null],
        ['no recorded request', [], null],
    ])('%s', (_, timings, expected) => {
        expect(getSingleRequestServerMs(timings, 40_000)).toBe(expected)
    })
})
