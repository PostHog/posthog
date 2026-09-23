import { useValues } from 'kea'

import { pluralize } from 'lib/utils/strings'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { isActorsQuery, isEventsQuery, isGroupsQuery, isSessionsQuery } from '~/queries/utils'

export function DataTableCount({ nouns }: { nouns?: [string, string] }): JSX.Element | null {
    const { totalCount, totalCountLoading, filteredCount, filteredCountLoading, hasActiveFilters, query } =
        useValues(dataNodeLogic)

    const loading = totalCountLoading || filteredCountLoading

    if (loading) {
        return <span className="text-muted-alt text-xs">Loading count...</span>
    }

    if (totalCount === null) {
        return null
    }

    const entityType = nouns ? { singular: nouns[0], plural: nouns[1] } : getEntityType(query)
    const displayFilteredCount = filteredCount !== null ? filteredCount : 0

    const text = hasActiveFilters
        ? `${pluralize(displayFilteredCount, entityType.singular, entityType.plural)} matched out of ${totalCount.toLocaleString()}`
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
