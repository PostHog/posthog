import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { ExperimentMetricMathType, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, CountPerActorMathType, FunnelVizType, PropertyMathType } from '~/types'

import { getFunnelQuery, getSumQuery, getTotalCountQuery } from './metricQueryUtils'

describe('metricQueryUtils', () => {
    const mockExperiment = {
        exposure_criteria: {
            filterTestAccounts: true,
        },
    }

    const mockEventConfig = {
        event: 'test_event',
        properties: [{ key: 'test', value: 'value' }],
    }

    describe('getTotalCountQuery', () => {
        it('generates correct query for mean total count metric', () => {
            const metric = {
                metric_type: ExperimentMetricType.MEAN,
                source: {
                    kind: NodeKind.EventsNode,
                    event: 'test_event',
                    math: ExperimentMetricMathType.TotalCount,
                },
            }

            const query = getTotalCountQuery(metric, mockExperiment)

            expect(query).toEqual({
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'test_event',
                        math: BaseMathType.UniqueUsers,
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'test_event',
                        math: CountPerActorMathType.Average,
                    },
                ],
                trendsFilter: {},
                filterTestAccounts: true,
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
            })
        })
    })

    describe('getSumQuery', () => {
        it('generates correct query for mean sum metric', () => {
            const metric = {
                metric_type: ExperimentMetricType.MEAN,
                source: {
                    kind: NodeKind.EventsNode,
                    event: 'test_event',
                    math: ExperimentMetricMathType.Sum,
                    math_property: 'revenue',
                },
            }

            const query = getSumQuery(metric, mockExperiment)

            expect(query).toEqual({
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'test_event',
                        math: BaseMathType.UniqueUsers,
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'test_event',
                        math: PropertyMathType.Sum,
                        math_property_type: 'numerical_event_properties',
                        math_property: 'revenue',
                    },
                ],
                trendsFilter: {},
                filterTestAccounts: true,
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
            })
        })
    })

    describe('getFunnelQuery', () => {
        it('generates correct query for funnel metric', () => {
            const metric = {
                metric_type: ExperimentMetricType.FUNNEL,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'test_event',
                    },
                ],
            }

            const query = getFunnelQuery(metric, mockEventConfig, mockExperiment)

            expect(query).toEqual({
                kind: NodeKind.FunnelsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'test_event',
                        properties: [{ key: 'test', value: 'value' }],
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'test_event',
                    },
                ],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Steps,
                },
                filterTestAccounts: true,
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                interval: 'day',
            })
        })

        it('uses default event when no eventConfig provided', () => {
            const metric = {
                metric_type: ExperimentMetricType.FUNNEL,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'test_event',
                    },
                ],
            }

            const query = getFunnelQuery(metric, null, mockExperiment)

            expect(query.series[0].event).toBe('$pageview')
            expect(query.series[0].properties).toEqual([])
        })
    })
})
