import clsx from 'clsx'
import { useValues } from 'kea'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { QuillSummarizeRecordingBar } from 'products/replay_vision/frontend/components/QuillSummarizeRecordingBar'
import { visionSurfaceShown } from 'products/replay_vision/frontend/utils/visionSurface'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { DebugModeBanner } from './DebugModeBanner'
import { RecordingCommentsList } from './RecordingCommentsList'
import { RecordingTitleBlock } from './RecordingTitleBlock'
import { WatchPanelTabs } from './WatchPanelTabs'
import { WatchPanelTabsWithObservations } from './WatchPanelTabsWithObservations'

export function WatchPanel(): JSX.Element | null {
    const { logicProps, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { debugMode, watchDebugDock, watchPanelCollapsed } = useValues(playerSettingsLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    if (!sessionRecordingId) {
        return null
    }
    const vision = visionSurfaceShown(logicProps)
    const debugDocked = debugMode && watchDebugDock === 'bottom'

    return (
        <div
            data-quill
            className={clsx(
                'flex flex-col gap-4 px-1 pt-3 pb-6 text-foreground isolate min-h-0 overflow-y-auto [&>*]:shrink-0',
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
