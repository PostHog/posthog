import { TraceMetricChangeUnitApi, TraceMetricKeyApi } from '../../generated/api.schemas'
import { formatTileChange, formatTileDetail, formatTileValue } from './formatTile'

describe('formatTile', () => {
    it.each<[TraceMetricKeyApi, number | null, string]>([
        [TraceMetricKeyApi.Cost, 1204, '$1,204.00'],
        [TraceMetricKeyApi.Cost, 0.004, '$0.004'],
        [TraceMetricKeyApi.Cost, null, '-'],
        [TraceMetricKeyApi.ErrorRate, 0.018, '1.8%'],
        [TraceMetricKeyApi.ErrorRate, 0, '0%'],
        [TraceMetricKeyApi.ErrorRate, null, '-'],
        [TraceMetricKeyApi.P95Latency, 4.2, '4.2s'],
        [TraceMetricKeyApi.P95Latency, 0.35, '350ms'],
        [TraceMetricKeyApi.P95Latency, 0, '0s'],
        [TraceMetricKeyApi.P95Latency, null, '-'],
        [TraceMetricKeyApi.Traces, 52118, '52,118'],
        [TraceMetricKeyApi.Users, 0, '0'],
        [TraceMetricKeyApi.Sessions, null, '-'],
    ])('formats a %s value of %p as %p', (key, value, expected) => {
        expect(formatTileValue(key, value)).toBe(expected)
    })

    it.each<[number, TraceMetricChangeUnitApi, string]>([
        [12, TraceMetricChangeUnitApi.Percent, '+12%'],
        [-4.6, TraceMetricChangeUnitApi.Percent, '−5%'],
        [0.4, TraceMetricChangeUnitApi.Percent, '0%'],
        [-0.4, TraceMetricChangeUnitApi.Percent, '0%'],
        [1500, TraceMetricChangeUnitApi.Percent, '+1,500%'],
        [-0.43, TraceMetricChangeUnitApi.Points, '−0.4pp'],
        [0.04, TraceMetricChangeUnitApi.Points, '0pp'],
        [2, TraceMetricChangeUnitApi.Seconds, '+2.0s'],
        [-1.25, TraceMetricChangeUnitApi.Seconds, '−1.3s'],
    ])('formats a change of %p %s as %p', (change, unit, expected) => {
        expect(formatTileChange(change, unit)).toBe(expected)
    })

    it.each<[Parameters<typeof formatTileDetail>[0], string | null]>([
        [{ detail: '1,147 errored traces', latencyQuantiles: null }, '1,147 errored traces'],
        [{ detail: null, latencyQuantiles: { p50Seconds: 1.4, p99Seconds: 8.9 } }, 'p50 1.4s · p99 8.9s'],
        [{ detail: null, latencyQuantiles: { p50Seconds: 0.42, p99Seconds: 4503 } }, 'p50 420ms · p99 1h\u00a015m'],
        [{ detail: null, latencyQuantiles: null }, null],
    ])('formats the detail of %p as %p', (tile, expected) => {
        expect(formatTileDetail(tile)).toBe(expected)
    })
})
