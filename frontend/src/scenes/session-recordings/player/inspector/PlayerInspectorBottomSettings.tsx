import './PlayerInspectorList.scss'

import { useActions, useValues } from 'kea'

import { BaseIcon, IconCheck } from '@posthog/icons'

import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { SettingsBar, SettingsMenu, SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from './playerInspectorLogic'

function HideProperties(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { hasEventsToDisplay } = useValues(inspectorLogic)
    const { hasEventsFiltersSelected } = useValues(miniFiltersLogic)

    const { hideNullValues } = useValues(userPreferencesLogic)
    const { setHideNullValues } = useActions(userPreferencesLogic)

    const { hidePostHogPropertiesInTable } = useValues(userPreferencesLogic)
    const { setHidePostHogPropertiesInTable } = useActions(userPreferencesLogic)

    return (
        <SettingsMenu
            items={[
                {
                    label: <>{hidePostHogPropertiesInTable ? <IconCheck /> : <BaseIcon />} Hide PostHog properties</>,
                    onClick: () => setHidePostHogPropertiesInTable(!hidePostHogPropertiesInTable),
                    active: hidePostHogPropertiesInTable,
                    disabledReason:
                        hasEventsToDisplay && hasEventsFiltersSelected ? undefined : 'There are no events in the list',
                },
                {
                    label: <>{hideNullValues ? <IconCheck /> : <BaseIcon />} Hide null values</>,
                    onClick: () => setHideNullValues(!hideNullValues),
                    active: hideNullValues,
                    disabledReason:
                        hasEventsToDisplay && hasEventsFiltersSelected ? undefined : 'There are no events in the list',
                },
            ]}
            label="Hide properties"
            highlightWhenActive={false}
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

    const hasEventsFiltersSelected = miniFiltersForType('events').some((x) => x.enabled)
    const hasEventsToDisplay = allItemsByItemType['events']?.length > 0

    return (
        <SettingsToggle
            title={
                showOnlyMatching
                    ? 'Show all events for this recording'
                    : 'Show only events that match the current filters'
            }
            label="Show only matching events"
            active={hasEventsToDisplay && showOnlyMatching && allowMatchingEventsFilter}
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
