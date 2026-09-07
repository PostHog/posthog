import { ExperimentExposureTimeSeries } from '~/queries/schema/schema-general'

import { buildExposureSeries } from './exposuresTransforms'

describe('buildExposureSeries', () => {
    it('passes the backend days through as labels, one series per variant', () => {
        const timeseries: ExperimentExposureTimeSeries[] = [
            { variant: 'control', days: ['2025-05-25', '2025-05-26'], exposure_counts: [10, 25] },
            { variant: 'test', days: ['2025-05-25', '2025-05-26'], exposure_counts: [12, 30] },
        ]

        const { labels, series } = buildExposureSeries(timeseries)

        expect(labels).toEqual(['2025-05-25', '2025-05-26'])
        expect(series).toEqual([
            { key: 'control', label: 'control', data: [10, 25] },
            { key: 'test', label: 'test', data: [12, 30] },
        ])
    })

    it('pads a single-day timeseries with a zeroed prior day so the chart draws a line', () => {
        const timeseries: ExperimentExposureTimeSeries[] = [
            { variant: 'control', days: ['2025-05-26'], exposure_counts: [10] },
            { variant: 'test', days: ['2025-05-26'], exposure_counts: [12] },
        ]

        const { labels, series } = buildExposureSeries(timeseries)

        expect(labels).toEqual(['2025-05-25', '2025-05-26'])
        expect(series).toEqual([
            { key: 'control', label: 'control', data: [0, 10] },
            { key: 'test', label: 'test', data: [0, 12] },
        ])
    })

    it('returns nothing for an empty timeseries', () => {
        expect(buildExposureSeries([])).toEqual({ labels: [], series: [] })
    })

    it('keeps every series the same length as the labels', () => {
        const timeseries: ExperimentExposureTimeSeries[] = [
            { variant: 'control', days: ['2025-05-26'], exposure_counts: [10] },
        ]

        const { labels, series } = buildExposureSeries(timeseries)

        expect(series.map((s) => s.data.length)).toEqual([labels.length])
    })
})
