import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { PersonType } from '~/types'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'
import { DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS, logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'

// Renders the Logs tab on the person profile. Mounted only when the tab is active
// (LemonTabs renders just the active tab's content), so `logsConfigLogic` only fetches
// the team's `logs_distinct_id_attribute_keys` on demand rather than on every team load.
// The config only drives the caption here — the query is scoped via `personId`, which the
// backend expands to the person's distinct ids and matches against the configured keys plus
// the built-in distinct-id conventions (the same keys the logs UI links as a person).
export function PersonLogsTab({ person }: { person: PersonType }): JSX.Element {
    const { logsConfig } = useValues(logsConfigLogic)
    const distinctIdAttributeKeys =
        logsConfig?.logs_distinct_id_attribute_keys ?? DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS

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
                    and other common distinct ID attributes.
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
                personId={String(person.uuid ?? person.id)}
                showFullScreenButton={false}
                showSavedViewsButton={false}
            />
        </div>
    )
}
