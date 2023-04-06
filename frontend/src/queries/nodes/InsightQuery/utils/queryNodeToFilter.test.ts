import { hiddenLegendItemsToKeys, queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { InsightType, LifecycleFilterType } from '~/types'
import { ShownAsValue } from 'lib/constants'
import { LifecycleQuery, NodeKind } from '~/queries/schema'

describe('queryNodeToFilter', () => {
    test('converts a query node to a filter', () => {
        const filters: Partial<LifecycleFilterType> = {
            entity_type: 'events',
            insight: InsightType.LIFECYCLE,
            shown_as: ShownAsValue.LIFECYCLE,
            toggledLifecycles: ['new', 'dormant'],
        }

        const query: LifecycleQuery = {
            kind: NodeKind.LifecycleQuery,
            lifecycleFilter: {
                shown_as: ShownAsValue.LIFECYCLE,
                toggledLifecycles: ['new', 'dormant'],
            },
            series: [],
        }

        const result = queryNodeToFilter(query)

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
