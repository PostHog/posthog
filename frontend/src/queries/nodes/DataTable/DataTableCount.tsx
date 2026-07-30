import { useValues } from 'kea'

import { pluralize } from 'lib/utils/strings'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { isActorsQuery, isEventsQuery, isGroupsQuery, isSessionsQuery } from '~/queries/utils'

export function DataTableCount(): JSX.Element | null {
    const {
        totalCount: loadedTotalCount,
        totalCountLoading,
        filteredCount,
        filteredCountLoading,
        hasActiveFilters,
        numberOfRows,
        query,
    } = useValues(dataNodeLogic)

    const loading = totalCountLoading || filteredCountLoading

    if (loading) {
        return <span className="text-muted-alt text-xs">Loading count...</span>
    }

    // A total below the number of rows already on screen can't be right, so don't show it
    const totalCount =
        loadedTotalCount !== null && numberOfRows !== null && numberOfRows > loadedTotalCount ? null : loadedTotalCount

    const entityType = getEntityType(query)

    if (hasActiveFilters) {
        if (filteredCount === null) {
            return null
        }
        // The counts come from two separate queries, so only put them side by side when the pair adds up
        const text =
            totalCount !== null && filteredCount <= totalCount
                ? `${pluralize(filteredCount, entityType.singular, entityType.plural)} matched out of ${totalCount.toLocaleString()}`
                : `${pluralize(filteredCount, entityType.singular, entityType.plural)} matched`
        return <span className="text-small">{text}</span>
    }

    if (totalCount === null) {
        return null
    }

    return (
        <span className="text-small">{`Total count: ${pluralize(totalCount, entityType.singular, entityType.plural)}`}</span>
    )
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
