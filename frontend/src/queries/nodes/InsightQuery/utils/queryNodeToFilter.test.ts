import { FunnelLayout } from 'lib/constants'

import { hiddenLegendItemsToKeys, queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelsQuery, LifecycleQuery, NodeKind, TrendsQuery } from '~/queries/schema'
import {
    BreakdownAttributionType,
    ChartDisplayType,
    FunnelConversionWindowTimeUnit,
    FunnelsFilterType,
    FunnelStepReference,
    FunnelVizType,
    InsightType,
    LifecycleFilterType,
    StepOrderValue,
    TrendsFilterType,
} from '~/types'

describe('queryNodeToFilter', () => {
    test('converts a query node to a filter', () => {
        const query: LifecycleQuery = {
            kind: NodeKind.LifecycleQuery,
            lifecycleFilter: {
                toggledLifecycles: ['new', 'dormant'],
            },
            series: [],
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<LifecycleFilterType> = {
            entity_type: 'events',
            insight: InsightType.LIFECYCLE,
            toggledLifecycles: ['new', 'dormant'],
        }
        expect(result).toEqual(filters)
    })

    test('converts a breakdownFilter into breakdown properties', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [],
            breakdownFilter: {
                breakdown: '$current_url',
                breakdown_normalize_url: false,
                breakdown_hide_other_aggregation: false,
            },
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<TrendsFilterType> = {
            entity_type: 'events',
            insight: InsightType.TRENDS,
            breakdown: '$current_url',
            breakdown_hide_other_aggregation: false,
            breakdown_normalize_url: false,
        }
        expect(result).toEqual(filters)
    })

    test('converts a trendsFilter into filter properties', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [],
            trendsFilter: {
                smoothingIntervals: 3,
                compare: true,
                formula: 'A + B',
                display: ChartDisplayType.ActionsBar,
                // breakdown_histogram_bin_count?: TrendsFilterLegacy['breakdown_histogram_bin_count']
                showLegend: true,
                aggregationAxisFormat: 'numeric',
                aggregationAxisPrefix: 'M',
                aggregationAxisPostfix: '$',
                decimalPlaces: 5,
                showValuesOnSeries: true,
                showLabelsOnSeries: true,
                showPercentStackView: true,
                // hidden_legend_indexes?: TrendsFilterLegacy['hidden_legend_indexes']
            },
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<TrendsFilterType> = {
            insight: InsightType.TRENDS,
            entity_type: 'events',
            hidden_legend_keys: undefined,
            interval: undefined,
            smoothing_intervals: 3,
            display: ChartDisplayType.ActionsBar,
            formula: 'A + B',
            compare: true,
            decimal_places: 5,
            aggregation_axis_format: 'numeric',
            aggregation_axis_prefix: 'M',
            aggregation_axis_postfix: '$',
            show_labels_on_series: true,
            show_percent_stack_view: true,
            show_legend: true,
            show_values_on_series: true,
        }
        expect(result).toEqual(filters)
    })

    test('converts a funnelsFilter into filter properties', () => {
        const query: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            funnelsFilter: {
                funnelVizType: FunnelVizType.Steps,
                funnelFromStep: 1,
                funnelToStep: 2,
                funnelStepReference: FunnelStepReference.total,
                breakdownAttributionType: BreakdownAttributionType.AllSteps,
                breakdownAttributionValue: 1,
                binCount: 'auto',
                funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                funnelWindowInterval: 7,
                funnelOrderType: StepOrderValue.ORDERED,
                exclusions: [
                    {
                        event: '$pageview',
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        funnelFromStep: 1,
                        funnelToStep: 2,
                    },
                    {
                        id: 3,
                        kind: NodeKind.ActionsNode,
                        name: 'Some action',
                        funnelFromStep: 1,
                        funnelToStep: 2,
                    },
                ],
                layout: FunnelLayout.horizontal,
            },
            series: [],
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<FunnelsFilterType> = {
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.Steps,
            funnel_from_step: 1,
            funnel_to_step: 2,
            funnel_step_reference: FunnelStepReference.total,
            breakdown_attribution_type: BreakdownAttributionType.AllSteps,
            breakdown_attribution_value: 1,
            bin_count: 'auto',
            funnel_window_interval_unit: FunnelConversionWindowTimeUnit.Day,
            funnel_window_interval: 7,
            funnel_order_type: StepOrderValue.ORDERED,
            exclusions: [
                {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    funnel_from_step: 1,
                    funnel_to_step: 2,
                },
                {
                    id: 3,
                    type: 'actions',
                    order: 1,
                    name: 'Some action',
                    funnel_from_step: 1,
                    funnel_to_step: 2,
                },
            ],
            layout: FunnelLayout.horizontal,
            interval: undefined,
            hidden_legend_keys: undefined,
            funnel_aggregate_by_hogql: undefined,
            entity_type: 'events',
        }
        expect(result).toEqual(filters)
    })
})

describe('hiddenLegendItemsToKeys', () => {
    it('handles undefined', () => {
        expect(hiddenLegendItemsToKeys(undefined)).toEqual(undefined)
    })

    it('converts hidden_legend_breakdowns', () => {
        expect(hiddenLegendItemsToKeys(['a'])).toEqual({ a: true })
        expect(hiddenLegendItemsToKeys(['a', 'b'])).toEqual({ a: true, b: true })
    })

    it('converts hidden_legend_indexes', () => {
        expect(hiddenLegendItemsToKeys([1])).toEqual({ '1': true })
        expect(hiddenLegendItemsToKeys([1, 2])).toEqual({ '1': true, '2': true })
    })
})
