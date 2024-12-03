import './PlayerInspectorList.scss'

import { useActions, useValues } from 'kea'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { SettingsBar, SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'

import { FilterableInspectorListItemTypes } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from './playerInspectorLogic'

function HideProperties(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { allItemsByItemType } = useValues(inspectorLogic)

    const { miniFiltersForType } = useValues(miniFiltersLogic)
    const { hidePostHogPropertiesInTable } = useValues(userPreferencesLogic)
    const { setHidePostHogPropertiesInTable } = useActions(userPreferencesLogic)

    const hasEventsFiltersSelected = miniFiltersForType(FilterableInspectorListItemTypes.EVENTS).some((x) => x.enabled)
    const hasEventsToDisplay = allItemsByItemType[FilterableInspectorListItemTypes.EVENTS]?.length > 0

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
                hasEventsToDisplay && hasEventsFiltersSelected ? undefined : 'There are no events in the list'
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
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { allItemsByItemType, allowMatchingEventsFilter } = useValues(inspectorLogic)

    const { showOnlyMatching, miniFiltersForType } = useValues(miniFiltersLogic)
    const { setShowOnlyMatching } = useActions(miniFiltersLogic)

    const hasEventsFiltersSelected = miniFiltersForType(FilterableInspectorListItemTypes.EVENTS).some((x) => x.enabled)
    const hasEventsToDisplay = allItemsByItemType[FilterableInspectorListItemTypes.EVENTS]?.length > 0

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
            disabledReason={
                hasEventsToDisplay && hasEventsFiltersSelected
                    ? allowMatchingEventsFilter
                        ? undefined
                        : 'There are no event filters to match against'
                    : 'There are no events in the list'
            }
        />
    )
}

export function PlayerInspectorBottomSettings(): JSX.Element {
    return (
        <SettingsBar border="top">
            <SyncScrolling />
            <ShowOnlyMatching />
            <HideProperties />
        </SettingsBar>
    )
}
