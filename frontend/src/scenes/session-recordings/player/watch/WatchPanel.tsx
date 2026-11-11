import clsx from 'clsx'
import { useValues } from 'kea'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { QuillSummarizeRecordingBar } from 'products/replay_vision/frontend/components/QuillSummarizeRecordingBar'
import { useVisionSurfaceShown } from 'products/replay_vision/frontend/utils/useVisionSurfaceShown'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { DebugModeBanner } from './DebugModeBanner'
import { RecordingCommentsList } from './RecordingCommentsList'
import { RecordingTitleBlock } from './RecordingTitleBlock'
import { WatchPanelTabs } from './WatchPanelTabs'
import { WatchPanelTabsWithObservations } from './WatchPanelTabsWithObservations'

export function WatchPanel(): JSX.Element | null {
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const vision = useVisionSurfaceShown()
    const { debugMode, watchDebugDock, watchPanelCollapsed } = useValues(playerSettingsLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    if (!sessionRecordingId) {
        return null
    }
    const debugDocked = debugMode && watchDebugDock === 'bottom'

    return (
        <div
            data-quill
            className={clsx(
                'flex flex-col gap-3 px-1 pt-2 pb-1.5 text-foreground isolate min-h-0 overflow-y-auto [&>*]:shrink-0',
                watchPanelCollapsed ? 'shrink-0' : 'flex-1'
            )}
            data-attr="watch-panel"
        >
            <DebugModeBanner />
            <RecordingTitleBlock actions={vision ? <QuillSummarizeRecordingBar /> : undefined} />
            {vision && dataProcessingAccepted ? (
                <WatchPanelTabsWithObservations sessionId={sessionRecordingId} debug={debugDocked} />
            ) : (
                <WatchPanelTabs debug={debugDocked} />
            )}
            <RecordingCommentsList sessionId={sessionRecordingId} />
        </div>
    )
}
