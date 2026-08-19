import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pluralize } from 'lib/utils/strings'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { isActorsQuery, isEventsQuery, isGroupsQuery, isSessionsQuery } from '~/queries/utils'

export function DataTableCount(): JSX.Element | null {
    const {
        totalCount,
        totalCountLoading,
        totalCountLoadFailed,
        filteredCount,
        filteredCountLoading,
        hasActiveFilters,
        query,
    } = useValues(dataNodeLogic)
    const { loadTotalCount } = useActions(dataNodeLogic)

    const loading = totalCountLoading || filteredCountLoading

    if (loading) {
        return <span className="text-muted-alt text-xs">Loading count...</span>
    }

    if (totalCount === null) {
        if (totalCountLoadFailed) {
            return (
                <span className="text-muted-alt text-xs">
                    Couldn't load count.{' '}
                    <LemonButton type="tertiary" size="xsmall" onClick={() => loadTotalCount()}>
                        Retry
                    </LemonButton>
                </span>
            )
        }
        return null
    }

    const entityType = getEntityType(query)
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
