import { deriveMetricsAlertPreview } from './metricsAlertPreview'

describe('deriveMetricsAlertPreview', () => {
    it('puts every series on the shared bucket grid with gaps, named like breach messages', () => {
        const preview = deriveMetricsAlertPreview([
            {
                metricName: 'queue.depth',
                labels: { region: 'eu', pod: 'a' },
                points: [
                    { time: '2026-09-19T10:05:00Z', value: 7 },
                    { time: '2026-09-19T10:00:00Z', value: 5 },
                ],
            },
            { clause: 'formula', labels: {}, points: [{ time: '2026-09-19T10:10:00Z', value: null }] },
        ])

        expect(preview?.rows).toEqual([
            { key: '0', label: 'queue.depth {pod=a, region=eu}', data: [5, 7, NaN] },
            { key: '1', label: 'formula', data: [NaN, NaN, NaN] },
        ])
        expect(preview?.labels).toHaveLength(3)
    })
})
