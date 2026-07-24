import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import {
    FilterLogicalOperator,
    LogPropertyFilter,
    PersonType,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'
import { DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS, logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'

// Renders the Logs tab on the person profile. Mounted only when the tab is active
// (LemonTabs renders just the active tab's content), so `logsConfigLogic` only fetches
// the team's `logs_distinct_id_attribute_keys` on demand rather than on every team load.
// While the config loads, falls back to the default keys — accurate for the vast majority
// of teams; non-default teams briefly see the wrong filter then resolve to the override.
export function PersonLogsTab({ person }: { person: PersonType }): JSX.Element {
    const { logsConfig } = useValues(logsConfigLogic)
    const distinctIdAttributeKeys =
        logsConfig?.logs_distinct_id_attribute_keys ?? DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS

    const pinnedFilters = useMemo((): UniversalFiltersGroup => {
        const keyFilters = distinctIdAttributeKeys.map(
            (key): LogPropertyFilter => ({
                key,
                type: PropertyFilterType.LogAttribute,
                operator: PropertyOperator.Exact,
                value: person.distinct_ids,
            })
        )
        return {
            type: FilterLogicalOperator.And,
            // A single key pins a plain filter; multiple keys pin a nested OR group so a
            // log matches when any configured attribute holds one of the distinct IDs.
            values: keyFilters.length === 1 ? keyFilters : [{ type: FilterLogicalOperator.Or, values: keyFilters }],
        }
    }, [distinctIdAttributeKeys, person.distinct_ids])

    return (
        <div className="flex flex-col h-[calc(100vh-16rem)] min-h-[25rem]">
            <p className="text-muted text-xs mb-2 flex items-center gap-1 flex-wrap">
                <span>
                    Scoped to this person via{' '}
                    {distinctIdAttributeKeys.map((key, index) => (
                        <span key={key}>
                            {index > 0 && ' or '}
                            <code>{key}</code>
                        </span>
                    ))}{' '}
                    log {distinctIdAttributeKeys.length === 1 ? 'attribute' : 'attributes'}.
                </span>
                <LemonButton
                    size="xsmall"
                    icon={<IconGear />}
                    tooltip="Change the log attributes used to link logs to a person"
                    to={urls.settings('environment-logs', 'logs-distinct-id-attribute-key')}
                />
            </p>
            <LogsViewer
                id={`person-${person.uuid ?? person.id}`}
                pinnedFilters={pinnedFilters}
                showFullScreenButton={false}
                showSavedViewsButton={false}
            />
        </div>
    )
}
