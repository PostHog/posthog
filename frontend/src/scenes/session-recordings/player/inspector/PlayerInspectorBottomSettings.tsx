import './PlayerInspectorList.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'

import { InspectorListItemType } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from './playerInspectorLogic'

function HideProperties(): JSX.Element | null {
    const { miniFiltersForType } = useValues(miniFiltersLogic)
    const { hidePostHogPropertiesInTable } = useValues(userPreferencesLogic)
    const { setHidePostHogPropertiesInTable } = useActions(userPreferencesLogic)

    return (
        <LemonButton
            status={hidePostHogPropertiesInTable ? 'danger' : 'default'}
            onClick={() => setHidePostHogPropertiesInTable(!hidePostHogPropertiesInTable)}
            size="xsmall"
            disabledReason={
                miniFiltersForType(InspectorListItemType.EVENTS).some((x) => x.enabled)
                    ? undefined
                    : 'There are no events in the list'
            }
        >
            Hide PostHog properties
        </LemonButton>
    )
}

function SyncScrolling(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { syncScrollPaused } = useValues(inspectorLogic)
    const { setSyncScrollPaused } = useActions(inspectorLogic)

    return (
        <LemonButton
            status={syncScrollPaused ? 'default' : 'danger'}
            size="xsmall"
            onClick={() => {
                setSyncScrollPaused(!syncScrollPaused)
            }}
        >
            Sync scrolling
        </LemonButton>
    )
}

function ShowOnlyMatching(): JSX.Element {
    const { showOnlyMatching } = useValues(miniFiltersLogic)
    const { setShowOnlyMatching } = useActions(miniFiltersLogic)

    return (
        <LemonButton
            status={showOnlyMatching ? 'danger' : 'default'}
            size="xsmall"
            onClick={() => {
                setShowOnlyMatching(!showOnlyMatching)
            }}
        >
            Show only matching events
        </LemonButton>
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
