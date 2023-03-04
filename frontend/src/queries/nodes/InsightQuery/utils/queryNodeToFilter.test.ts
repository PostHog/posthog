import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
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
