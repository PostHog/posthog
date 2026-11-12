import { ExperimentEventExposureConfig, ExperimentExposureTimeSeries, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { buildExposureSeries, getExposureCriteriaLabel } from './exposuresTransforms'

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

describe('getExposureCriteriaLabel', () => {
    it.each<[string, AnyPropertyFilter[] | undefined, string]>([
        ['no config', undefined, 'Default ($experiment_exposure)'],
        ['an unfiltered $feature_flag_called config', [], 'Default ($experiment_exposure)'],
        [
            'a filtered $feature_flag_called config',
            [{ key: 'plan', value: ['pro'], operator: PropertyOperator.Exact, type: PropertyFilterType.Person }],
            'Default ($experiment_exposure), with filters',
        ],
    ])('labels %s', (_, properties, expected) => {
        const exposureConfig: ExperimentEventExposureConfig | undefined = properties
            ? { kind: NodeKind.ExperimentEventExposureConfig, event: '$feature_flag_called', properties }
            : undefined

        expect(getExposureCriteriaLabel({ exposure_config: exposureConfig }, '$experiment_exposure')).toEqual(expected)
    })
})
