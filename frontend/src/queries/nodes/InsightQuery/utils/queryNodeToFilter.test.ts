import { hiddenLegendItemsToKeys, queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { LifecycleQuery, NodeKind, TrendsQuery } from '~/queries/schema'
import { ChartDisplayType, InsightType, LifecycleFilterType, TrendsFilterType } from '~/types'

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
                // show_legend?: TrendsFilterLegacy['show_legend']
                aggregationAxisFormat: 'numeric',
                aggregationAxisPrefix: 'M',
                aggregationAxisPostfix: '$',
                decimalPlaces: 5,
                // show_values_on_series?: TrendsFilterLegacy['show_values_on_series']
                // show_labels_on_series?: TrendsFilterLegacy['show_labels_on_series']
                // show_percent_stack_view?: TrendsFilterLegacy['show_percent_stack_view']
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
