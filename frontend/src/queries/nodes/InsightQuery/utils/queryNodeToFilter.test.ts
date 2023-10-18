import { hiddenLegendItemsToKeys, queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { InsightType, LifecycleFilterType } from '~/types'
import { LifecycleQuery, NodeKind } from '~/queries/schema'

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
