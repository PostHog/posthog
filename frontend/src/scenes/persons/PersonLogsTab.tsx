import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { FilterLogicalOperator, LogPropertyFilter, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'
import { DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS, logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'

// Renders the Logs tab on the person profile. Mounted only when the tab is active
// (LemonTabs renders just the active tab's content), so `logsConfigLogic` only fetches
// the team's `logs_distinct_id_attribute_keys` on demand rather than on every team load.
// While the config loads, falls back to the default key list — accurate for the vast
// majority of teams; non-default teams briefly see the wrong filter then resolve to the
// override.
export function PersonLogsTab({ person }: { person: PersonType }): JSX.Element {
    const { logsConfig } = useValues(logsConfigLogic)
    const distinctIdAttributeKeys =
        logsConfig?.logs_distinct_id_attribute_keys ?? DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS
    const isCustomized = !equal(distinctIdAttributeKeys, DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS)

    const pinnedFilters = useMemo(
        () => ({
            type: FilterLogicalOperator.And,
            values: [
                {
                    // `key` is the first configured attribute — kept populated so any
                    // generic property-filter consumer (chip renderer, taxonomic picker,
                    // saved-view serialization) sees a valid single-key filter. The
                    // `keys` array is the priority-ordered fallback list that the backend
                    // compiles to `coalesce(attributes[k1__str], attributes[k2__str], …)`.
                    key: distinctIdAttributeKeys[0],
                    keys: distinctIdAttributeKeys,
                    type: PropertyFilterType.LogAttribute,
                    operator: PropertyOperator.Exact,
                    value: person.distinct_ids,
                } as LogPropertyFilter,
            ],
        }),
        [distinctIdAttributeKeys, person.distinct_ids]
    )

    const settingsUrl = urls.settings('environment-logs', 'logs-distinct-id-attribute-key')

    return (
        <div className="flex flex-col h-[calc(100vh-16rem)] min-h-[25rem]">
            <p className="text-muted text-xs mb-2">
                Scoped to this person via the{' '}
                {distinctIdAttributeKeys.map((key, i) => (
                    <span key={key}>
                        {i > 0 && ', '}
                        <code>{key}</code>
                    </span>
                ))}{' '}
                log {distinctIdAttributeKeys.length === 1 ? 'attribute' : 'attributes (priority order)'}.{' '}
                {isCustomized && (
                    <>
                        Customised from default <code>{DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS[0]}</code>.{' '}
                    </>
                )}
                <Link to={settingsUrl}>Link logs to a person →</Link>
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
