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

    return miniFiltersForType(InspectorListItemType.EVENTS).some((x) => x.enabled) ? (
        <LemonButton
            status={hidePostHogPropertiesInTable ? 'danger' : 'default'}
            onClick={() => setHidePostHogPropertiesInTable(!hidePostHogPropertiesInTable)}
            size="xsmall"
        >
            Hide PostHog properties
        </LemonButton>
    ) : null
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

export function PlayerInspectorBottomSettings(): JSX.Element {
    return (
        <div className="flex flex-row bg-bg-3000 w-full overflow-hidden border-t px-2 py-1 font-light text-small">
            <SyncScrolling />
            <HideProperties />
        </div>
    )
}
