import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import type { ActionsNode, EventsNode, ExperimentMetric } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { ChartDisplayType, ExperimentMetricMathType, PropertyMathType } from '~/types'

import { getFilter, getQuery } from './metricQueryUtils'

describe('getFilter', () => {
    it('returns the correct filter for an event', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: 'total',
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
            } as EventsNode,
        }
        const filter = getFilter(metric)
        expect(filter).toEqual({
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    math: 'total',
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
                    kind: NodeKind.EventsNode,
                },
            ],
            actions: [],
            data_warehouse: [],
        })
    })
    it('returns the correct filter for an action', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: 8,
                name: 'jan-16-running payment action',
                math: 'total',
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
            } as ActionsNode,
        }
        const filter = getFilter(metric)
        expect(filter).toEqual({
            events: [],
            actions: [
                {
                    id: 8,
                    name: 'jan-16-running payment action',
                    type: 'actions',
                    math: 'total',
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
                    kind: NodeKind.ActionsNode,
                },
            ],
            data_warehouse: [],
        })
    })
})

describe('getQuery', () => {
    it('returns the correct query for a funnel metric', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.FUNNEL,
            series: [
                {
                    event: 'purchase',
                    kind: NodeKind.EventsNode,
                    name: 'purchase',
                },
            ],
        }

        const query = getQuery({
            filterTestAccounts: false,
        })(metric)

        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.FunnelsQuery,
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                funnelsFilter: {
                    layout: FunnelLayout.horizontal,
                },
                filterTestAccounts: false,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'purchase',
                        name: 'purchase',
                    },
                ],
            })
        )
    })

    it('returns the correct query for a count metric', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.TotalCount,
            },
        }

        const query = getQuery({
            filterTestAccounts: false,
        })(metric)

        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                filterTestAccounts: false,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                        math: ExperimentMetricMathType.TotalCount,
                    },
                ],
            })
        )
    })

    it('returns the correct query for a mean metric with sum math type', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.Sum,
                math_property: 'property_value',
            },
        }

        const query = getQuery({
            filterTestAccounts: true,
        })(metric)
        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                filterTestAccounts: true,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        math: PropertyMathType.Sum,
                        math_property: 'property_value',
                    },
                ],
            })
        )
    })

    it('returns the correct query for a mean metric with unique sessions math type', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.UniqueSessions,
            },
        }
        const query = getQuery({
            filterTestAccounts: true,
        })(metric)
        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                filterTestAccounts: true,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        math: ExperimentMetricMathType.UniqueSessions,
                    },
                ],
            })
        )
    })

    it('returns undefined for unsupported metric types', () => {
        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: 'unsupported_type' as ExperimentMetricType,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
            },
        }

        const query = getQuery({
            filterTestAccounts: false,
        })(metric as ExperimentMetric)
        expect(query).toBeUndefined()
    })

    it('returns the correct query for a mean metric with an action source', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: 123,
                name: 'test action',
                math: ExperimentMetricMathType.Sum,
                math_property: 'property_value',
            },
        }

        const query = getQuery({
            filterTestAccounts: true,
        })(metric)
        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                filterTestAccounts: true,
                series: [
                    {
                        kind: NodeKind.ActionsNode,
                        id: 123,
                        name: 'test action',
                        math: PropertyMathType.Sum,
                        math_property: 'property_value',
                    },
                ],
            })
        )
    })
})
