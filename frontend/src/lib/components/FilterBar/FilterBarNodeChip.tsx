import { useValues } from 'kea'

import { FilterLogicalOperator } from '~/types'

import { FilterBarChip } from './FilterBarChip'
import { FilterBarEventChip } from './FilterBarEventChip'
import { filterBarLogic } from './filterBarLogic'
import { isEventNode } from './filterBarTree'
import { FilterBarEventNode, FilterBarItem } from './filterBarTypes'

/** Groups as deep as "A or (B and C)" cover the two levels people build. A stored deeper group still renders. */
const MAX_WRAP_DEPTH = 2

/** One filter or event. `parentType` is the operator that joins the row to its siblings. */
export function FilterBarNodeChip({
    node,
    parentType,
    depth,
}: {
    node: FilterBarItem | FilterBarEventNode
    parentType: FilterLogicalOperator
    depth: number
}): JSX.Element {
    const { groupsEnabled } = useValues(filterBarLogic)
    const opposite = parentType === FilterLogicalOperator.Or ? FilterLogicalOperator.And : FilterLogicalOperator.Or
    const wrapType = groupsEnabled && depth < MAX_WRAP_DEPTH ? opposite : null
    return isEventNode(node) ? (
        <FilterBarEventChip node={node} wrapType={wrapType} />
    ) : (
        <FilterBarChip item={node} wrapType={wrapType} />
    )
}
