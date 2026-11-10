import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { QuillSummarizeRecordingBar } from 'products/replay_vision/frontend/components/QuillSummarizeRecordingBar'
import { useVisionSurfaceShown } from 'products/replay_vision/frontend/utils/useVisionSurfaceShown'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { RecordingCommentsList } from './RecordingCommentsList'
import { RecordingTitleBlock } from './RecordingTitleBlock'
import { WatchPanelSections } from './WatchPanelSections'
import { WatchPanelSectionsWithObservations } from './WatchPanelSectionsWithObservations'

export const WATCH_PANEL_COLLAPSED_SIZE = '2.5rem'

export function WatchPanel(): JSX.Element | null {
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const vision = useVisionSurfaceShown()
    const { debugMode, watchDebugDock, watchPanelCollapsed } = useValues(playerSettingsLogic)
    const { setWatchPanelCollapsed } = useActions(playerSettingsLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    if (!sessionRecordingId) {
        return null
    }
    const debugDocked = debugMode && watchDebugDock === 'bottom'
    const actions = vision ? <QuillSummarizeRecordingBar /> : undefined
    const toggle = (
        <Button
            size="icon"
            onClick={() => setWatchPanelCollapsed(!watchPanelCollapsed)}
            tooltip={watchPanelCollapsed ? 'Expand' : 'Collapse'}
            aria-label={watchPanelCollapsed ? 'Expand' : 'Collapse'}
            data-attr="watch-panel-collapse"
        >
            <IconChevronDown className={watchPanelCollapsed ? 'rotate-180' : undefined} />
        </Button>
    )
    if (watchPanelCollapsed) {
        return <RecordingTitleBlock compact actions={actions} trailingActions={toggle} />
    }

    return (
        <div
            data-quill
            className="flex flex-col gap-3 px-1 pt-2 pb-1.5 text-foreground isolate h-full min-h-0 overflow-y-auto [&>*]:shrink-0"
            data-attr="watch-panel"
        >
            <RecordingTitleBlock actions={actions} trailingActions={toggle} />
            {vision && dataProcessingAccepted ? (
                <WatchPanelSectionsWithObservations sessionId={sessionRecordingId} debug={debugDocked} />
            ) : (
                <WatchPanelSections debug={debugDocked} />
            )}
            <RecordingCommentsList sessionId={sessionRecordingId} />
        </div>
    )
}
