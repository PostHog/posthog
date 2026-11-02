import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { CohortType, FilterLogicalOperator, PropertyFilterType, AnyPropertyFilter } from '~/types'

import {
    cohortNameForFilter,
    fieldFromFilter,
    fieldLabelForKey,
    filterValues,
    operatorLabelForFilter,
} from './filterBarFields'
import { isEventNode, isGroupNode } from './filterBarTree'
import { FilterBarNode } from './filterBarTypes'

type CohortsById = Partial<Record<CohortType['id'], CohortType>>

function filterSentence(filter: AnyPropertyFilter, cohortsById: CohortsById): string {
    const field = fieldFromFilter(filter)
    if (!field) {
        return formatPropertyLabel(filter, cohortsById).trim() || String(filter.key)
    }
    if (filter.type === PropertyFilterType.HogQL) {
        return `SQL ${filter.key}`
    }
    if (filter.type === PropertyFilterType.Cohort) {
        return `${field.label} ${operatorLabelForFilter(filter)} ${cohortNameForFilter(filter, cohortsById)}`
    }
    const operator = operatorLabelForFilter(filter).replace(/ any of$| none of$/, '')
    const joiner = operatorLabelForFilter(filter).endsWith('none of') ? ' nor ' : ' or '
    return [field.label, operator, filterValues(filter).join(joiner)].filter(Boolean).join(' ')
}

function nodeSentence(node: FilterBarNode, cohortsById: CohortsById): string {
    if (isGroupNode(node)) {
        const joined = joinSentences(node.children, node.type, cohortsById)
        return node.children.length > 1 ? `(${joined})` : joined
    }
    if (isEventNode(node)) {
        const name = fieldLabelForKey('events', node.event.name ?? String(node.event.id))
        const verb = node.event.negation ? 'did not perform' : 'performed'
        const narrowed = node.items.map((item) => filterSentence(item.filter, cohortsById)).join(' and ')
        return narrowed ? `${verb} ${name} with ${narrowed}` : `${verb} ${name}`
    }
    return filterSentence(node.filter, cohortsById)
}

function joinSentences(nodes: FilterBarNode[], type: FilterLogicalOperator, cohortsById: CohortsById): string {
    return nodes
        .map((node) => nodeSentence(node, cohortsById))
        .join(type === FilterLogicalOperator.Or ? ' or ' : ' and ')
}

/** The whole filter as one sentence, so a person can read how the and/or nesting resolves without tracing it. */
export function filterBarSummary(nodes: FilterBarNode[], cohortsById: CohortsById = {}): string {
    const only = nodes.length === 1 ? nodes[0] : null
    const sentence =
        only && isGroupNode(only)
            ? joinSentences(only.children, only.type, cohortsById)
            : joinSentences(nodes, FilterLogicalOperator.And, cohortsById)
    return capitalizeFirstLetter(sentence)
}
