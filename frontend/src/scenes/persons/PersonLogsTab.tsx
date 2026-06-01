import { useValues } from 'kea'
import { useMemo } from 'react'

import { FilterLogicalOperator, LogPropertyFilter, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'
import { DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY, logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'

// Renders the Logs tab on the person profile. Mounted only when the tab is active
// (LemonTabs renders just the active tab's content), so `logsConfigLogic` only fetches
// the team's `logs_distinct_id_attribute_key` on demand rather than on every team load.
// While the config loads, falls back to the default key — accurate for the vast majority
// of teams; non-default teams briefly see the wrong filter then resolve to the override.
export function PersonLogsTab({ person }: { person: PersonType }): JSX.Element {
    const { logsConfig } = useValues(logsConfigLogic)
    const distinctIdAttributeKey = logsConfig?.logs_distinct_id_attribute_key ?? DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY

    const pinnedFilters = useMemo(
        () => ({
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: distinctIdAttributeKey,
                    type: PropertyFilterType.LogAttribute,
                    operator: PropertyOperator.Exact,
                    value: person.distinct_ids,
                } as LogPropertyFilter,
            ],
        }),
        [distinctIdAttributeKey, person.distinct_ids]
    )

    return (
        <div className="flex flex-col h-[calc(100vh-16rem)] min-h-[25rem]">
            <LogsViewer
                id={`person-${person.uuid ?? person.id}`}
                pinnedFilters={pinnedFilters}
                showFullScreenButton={false}
                showSavedViewsButton={false}
            />
        </div>
    )
}
