import './PlayerInspectorList.scss'

import { useActions, useValues } from 'kea'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'

import { InspectorListItemType } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from './playerInspectorLogic'

function HideProperties(): JSX.Element | null {
    const { miniFiltersForType } = useValues(miniFiltersLogic)
    const { hidePostHogPropertiesInTable } = useValues(userPreferencesLogic)
    const { setHidePostHogPropertiesInTable } = useActions(userPreferencesLogic)

    return (
        <SettingsToggle
            title={
                hidePostHogPropertiesInTable
                    ? 'Do not show PostHog properties in expanded events'
                    : 'Show PostHog properties in expanded events'
            }
            label="Hide PostHog properties"
            onClick={() => setHidePostHogPropertiesInTable(!hidePostHogPropertiesInTable)}
            disabledReason={
                miniFiltersForType(InspectorListItemType.EVENTS).some((x) => x.enabled)
                    ? undefined
                    : 'There are no events in the list'
            }
            active={hidePostHogPropertiesInTable}
        />
    )
}

function SyncScrolling(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { syncScrollPaused } = useValues(inspectorLogic)
    const { setSyncScrollPaused } = useActions(inspectorLogic)

    return (
        <SettingsToggle
            title={
                syncScrollPaused
                    ? 'Scroll the activity list in sync with playback'
                    : 'Do not auto-scroll the activity list in sync with playback'
            }
            label="Sync scrolling"
            onClick={() => {
                setSyncScrollPaused(!syncScrollPaused)
            }}
            active={!syncScrollPaused}
        />
    )
}

function ShowOnlyMatching(): JSX.Element {
    const { showOnlyMatching } = useValues(miniFiltersLogic)
    const { setShowOnlyMatching } = useActions(miniFiltersLogic)

    return (
        <SettingsToggle
            title={
                showOnlyMatching
                    ? 'Show all events for this recording'
                    : 'Show only events that match the current filters'
            }
            label="Show only matching events"
            active={showOnlyMatching}
            onClick={() => {
                setShowOnlyMatching(!showOnlyMatching)
            }}
        />
    )
}

export function PlayerInspectorBottomSettings(): JSX.Element {
    return (
        <div className="flex flex-row bg-bg-3000 w-full overflow-hidden border-t px-2 py-1 font-light text-small">
            <SyncScrolling />
            <ShowOnlyMatching />
            <HideProperties />
        </div>
    )
}
