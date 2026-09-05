import { useValues } from 'kea'

import { pluralize } from 'lib/utils/strings'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { isActorsQuery, isEventsQuery, isGroupsQuery, isSessionsQuery } from '~/queries/utils'

export function DataTableCount(): JSX.Element | null {
    const { totalCount, totalCountLoading, filteredCount, filteredCountLoading, hasActiveFilters, query } =
        useValues(dataNodeLogic)

    const loading = totalCountLoading || filteredCountLoading

    if (loading) {
        return <span className="text-muted-alt text-xs">Loading count...</span>
    }

    if (totalCount === null) {
        return null
    }

    const entityType = getEntityType(query)

    // A null filtered count means the count query failed or has no result, not zero matches.
    // Fall back to the total count so we never show "0 matched" while the real number is unknown.
    const text =
        hasActiveFilters && filteredCount !== null
            ? `${pluralize(filteredCount, entityType.singular, entityType.plural)} matched out of ${totalCount.toLocaleString()}`
            : `Total count: ${pluralize(totalCount, entityType.singular, entityType.plural)}`

    return <span className="text-small">{text}</span>
}

function getEntityType(query: any): { singular: string; plural: string } {
    if (isActorsQuery(query)) {
        return { singular: 'person', plural: 'persons' }
    }
    if (isEventsQuery(query)) {
        return { singular: 'event', plural: 'events' }
    }
    if (isGroupsQuery(query)) {
        return { singular: 'group', plural: 'groups' }
    }
    if (isSessionsQuery(query)) {
        return { singular: 'session', plural: 'sessions' }
    }
    return { singular: 'row', plural: 'rows' }
}
