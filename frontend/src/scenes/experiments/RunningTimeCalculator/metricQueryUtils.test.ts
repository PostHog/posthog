import { dayjs } from 'lib/dayjs'

import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, CountPerActorMathType } from '~/types'

import { getFunnelQuery, getSumQuery, getTotalCountQuery } from './metricQueryUtils'

const mockMetric = {
    id: 'metric1',
    name: 'Test Metric',
    metric_type: 'mean',
    source: {
        kind: NodeKind.EventsNode,
        event: 'test_event',
        math: CountPerActorMathType.Average,
    },
} as any

const mockExperiment = {
    exposure_criteria: { filterTestAccounts: true },
    id: 'test-experiment',
    name: 'Test Experiment',
    description: '',
    start_date: null,
    end_date: null,
    feature_flag_key: 'test-flag',
    parameters: {},
    filters: {},
    archived: false,
    created_at: '2023-01-01T00:00:00Z',
    created_by: null,
    updated_at: '2023-01-01T00:00:00Z',
    metrics: [],
    saved_metrics: [],
} as any

const mockEventConfig = {
    event: 'custom_event',
    properties: [{ key: 'foo', value: 'bar' }],
} as any

describe('getTotalCountQuery', () => {
    it('returns correct query with eventConfig and filterTestAccounts true', () => {
        const result = getTotalCountQuery(mockMetric, mockExperiment, mockEventConfig)
        expect(result.kind).toBe(NodeKind.TrendsQuery)
        expect(result.series[0]).toMatchObject({
            kind: NodeKind.EventsNode,
            event: 'custom_event',
            properties: [{ key: 'foo', value: 'bar' }],
            math: BaseMathType.UniqueUsers,
        })
        expect(result.series[1].math).toBe(CountPerActorMathType.Average)
        expect(result.filterTestAccounts).toBe(true)
        expect(result.dateRange!.date_from).toContain(dayjs().subtract(14, 'day').format('YYYY-MM-DD')) // 14 is the default
        expect(result.dateRange!.date_to).toContain(dayjs().format('YYYY-MM-DD'))
        expect(result.dateRange!.explicitDate).toBe(true)
    })

    it('defaults event and properties if eventConfig is null', () => {
        const result = getTotalCountQuery(mockMetric, mockExperiment, null)
        if ('event' in result.series[0]) {
            expect(result.series[0].event).toBe('$pageview')
            expect(result.series[0].properties).toEqual([])
        } else {
            throw new Error('series[0] is not an EventsNode')
        }
    })

    it('sets filterTestAccounts to false if not set', () => {
        const experiment = { exposure_criteria: {} } as any
        const result = getTotalCountQuery(mockMetric, experiment, null)
        expect(result.filterTestAccounts).toBe(false)
    })

    it('handles missing exposure_criteria gracefully', () => {
        const experiment = {} as any
        const result = getTotalCountQuery(mockMetric, experiment, null)
        expect(result.filterTestAccounts).toBe(false)
    })
})

describe('getSumQuery', () => {
    it('returns correct query with eventConfig and filterTestAccounts true (MEAN metric)', () => {
        const metric = {
            ...mockMetric,
            metric_type: 'mean',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
                math_property: 'some_property',
            },
        }
        const result = getSumQuery(metric, mockExperiment, mockEventConfig)
        expect(result.kind).toBe(NodeKind.TrendsQuery)
        if ('event' in result.series[0]) {
            expect(result.series[0].event).toBe('custom_event')
            expect(result.series[0].properties).toEqual([{ key: 'foo', value: 'bar' }])
            expect(result.series[0].math).toBe(BaseMathType.UniqueUsers)
        } else {
            throw new Error('series[0] is not an EventsNode')
        }
        expect(result.series[1].math).toBe('sum')
        expect(result.series[1].math_property).toBe('some_property')
        expect(result.series[1].math_property_type).toBe('numerical_event_properties')
        expect(result.filterTestAccounts).toBe(true)
        expect(result.dateRange!.date_from).toContain(dayjs().subtract(14, 'day').format('YYYY-MM-DD'))
        expect(result.dateRange!.date_to).toContain(dayjs().format('YYYY-MM-DD'))
        expect(result.dateRange!.explicitDate).toBe(true)
    })

    it('defaults event and properties if eventConfig is null', () => {
        const metric = {
            ...mockMetric,
            metric_type: 'mean',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
                math_property: 'some_property',
            },
        }
        const result = getSumQuery(metric, mockExperiment, null)
        if ('event' in result.series[0]) {
            expect(result.series[0].event).toBe('$pageview')
            expect(result.series[0].properties).toEqual([])
        } else {
            throw new Error('series[0] is not an EventsNode')
        }
    })

    it('sets filterTestAccounts to false if not set', () => {
        const experiment = { exposure_criteria: {} } as any
        const metric = {
            ...mockMetric,
            metric_type: 'mean',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
                math_property: 'some_property',
            },
        }
        const result = getSumQuery(metric, experiment, null)
        expect(result.filterTestAccounts).toBe(false)
    })

    it('handles missing exposure_criteria gracefully', () => {
        const experiment = {} as any
        const metric = {
            ...mockMetric,
            metric_type: 'mean',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
                math_property: 'some_property',
            },
        }
        const result = getSumQuery(metric, experiment, null)
        expect(result.filterTestAccounts).toBe(false)
    })

    it('throws for unsupported metric_type', () => {
        const metric = {
            ...mockMetric,
            metric_type: 'count',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
            },
        }
        expect(() => getSumQuery(metric, mockExperiment, mockEventConfig)).toThrow('Unsupported metric type: count')
    })
})

describe('getFunnelQuery', () => {
    it('returns correct query with eventConfig and filterTestAccounts true', () => {
        const metric = {
            ...mockMetric,
            metric_type: 'mean',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
            },
        }
        const result = getFunnelQuery(metric, mockEventConfig, mockExperiment)
        expect(result.kind).toBe(NodeKind.FunnelsQuery)
        if ('event' in result.series[0]) {
            expect(result.series[0].event).toBe('custom_event')
            expect(result.series[0].properties).toEqual([{ key: 'foo', value: 'bar' }])
        } else {
            throw new Error('series[0] is not an EventsNode')
        }
        expect(result.series[1].kind).toBe(NodeKind.EventsNode)
        expect(result.filterTestAccounts).toBe(true)
        expect(result.dateRange!.date_from).toContain(dayjs().subtract(14, 'day').format('YYYY-MM-DD'))
        expect(result.dateRange!.date_to).toContain(dayjs().format('YYYY-MM-DD'))
        expect(result.dateRange!.explicitDate).toBe(true)
        expect(result.interval).toBe('day')
        expect(result.funnelsFilter!.funnelVizType).toBe('steps')
    })

    it('defaults event and properties if eventConfig is null', () => {
        const metric = {
            ...mockMetric,
            metric_type: 'mean',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
            },
        }
        const result = getFunnelQuery(metric, null, mockExperiment)
        if ('event' in result.series[0]) {
            expect(result.series[0].event).toBe('$pageview')
            expect(result.series[0].properties).toEqual([])
        } else {
            throw new Error('series[0] is not an EventsNode')
        }
    })

    it('sets filterTestAccounts to false if not set', () => {
        const experiment = { exposure_criteria: {} } as any
        const metric = {
            ...mockMetric,
            metric_type: 'mean',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
            },
        }
        const result = getFunnelQuery(metric, null, experiment)
        expect(result.filterTestAccounts).toBe(false)
    })

    it('handles missing exposure_criteria gracefully', () => {
        const experiment = {} as any
        const metric = {
            ...mockMetric,
            metric_type: 'mean',
            source: {
                kind: NodeKind.EventsNode,
                event: 'test_event',
                math: CountPerActorMathType.Average,
            },
        }
        const result = getFunnelQuery(metric, null, experiment)
        expect(result.filterTestAccounts).toBe(false)
    })
})
