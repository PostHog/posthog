import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

type WebAnalyticsEventType = '$pageview' | '$screen'

const DEFAULT_EVENT_TYPES: WebAnalyticsEventType[] = ['$pageview', '$screen']

export function WebAnalyticsEventTypesSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const savedEventTypes = (currentTeam?.web_analytics_event_types as WebAnalyticsEventType[] | undefined) ?? []
    const effectiveEventTypes = savedEventTypes.length > 0 ? savedEventTypes : DEFAULT_EVENT_TYPES
    const [selectedEventTypes, setSelectedEventTypes] = useState<WebAnalyticsEventType[]>(effectiveEventTypes)

    const handleToggle = (eventType: WebAnalyticsEventType): void => {
        setSelectedEventTypes((prev) => {
            if (prev.includes(eventType)) {
                // Don't allow deselecting if it's the last one
                if (prev.length === 1) {
                    return prev
                }
                return prev.filter((t) => t !== eventType)
            }
            return [...prev, eventType]
        })
    }

    const handleSave = (): void => {
        updateCurrentTeam({ web_analytics_event_types: selectedEventTypes })
    }

    const hasChanges = JSON.stringify(selectedEventTypes.sort()) !== JSON.stringify(effectiveEventTypes.slice().sort())

    return (
        <>
            <p>
                Choose which event types to include in Web Analytics queries. When both are selected, data from both
                pageviews and screen events will be combined using the appropriate path property for each.
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.WebAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <div className="flex flex-col gap-2 my-4">
                    <LemonCheckbox
                        checked={selectedEventTypes.includes('$pageview')}
                        onChange={() => handleToggle('$pageview')}
                        label={
                            <span>
                                Pageviews (<code>$pageview</code>) - Uses <code>$pathname</code> for path breakdown
                            </span>
                        }
                        disabled={selectedEventTypes.length === 1 && selectedEventTypes.includes('$pageview')}
                    />
                    <LemonCheckbox
                        checked={selectedEventTypes.includes('$screen')}
                        onChange={() => handleToggle('$screen')}
                        label={
                            <span>
                                Screen events (<code>$screen</code>) - Uses <code>$screen_name</code> for path breakdown
                            </span>
                        }
                        disabled={selectedEventTypes.length === 1 && selectedEventTypes.includes('$screen')}
                    />
                </div>
            </AccessControlAction>
            <div className="mt-4">
                <AccessControlAction
                    resourceType={AccessControlResourceType.WebAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        onClick={handleSave}
                        disabledReason={!hasChanges ? 'No changes to save' : undefined}
                    >
                        Save
                    </LemonButton>
                </AccessControlAction>
            </div>
        </>
    )
}
