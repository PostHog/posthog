import { useValues } from 'kea'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'

import { SummarizeRecordingBar } from 'products/replay_vision/frontend/components/SummarizeRecordingBar'
import { visionSurfaceShown } from 'products/replay_vision/frontend/utils/visionSurface'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { DebugModeBanner } from './DebugModeBanner'
import { RecordingCommentsList } from './RecordingCommentsList'
import { RecordingDebugSection } from './RecordingDebugSection'
import { RecordingObservationsSection } from './RecordingObservationsSection'
import { RecordingOverviewDisclosure } from './RecordingOverviewDisclosure'
import { RecordingTitleBlock } from './RecordingTitleBlock'

export function WatchPanel({
    summaryActions,
}: {
    /** Recording actions the host places beside the summarize button. */
    summaryActions?: React.ReactNode
}): JSX.Element | null {
    const { logicProps, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { debugMode, watchDebugDock } = useValues(playerSettingsLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    if (!sessionRecordingId) {
        return null
    }
    const vision = visionSurfaceShown(logicProps)

    return (
        <div className="flex flex-col gap-4 px-1 pt-3 pb-6" data-attr="watch-panel">
            <DebugModeBanner />
            <RecordingTitleBlock
                actions={vision ? <SummarizeRecordingBar inline extraActions={summaryActions} /> : summaryActions}
            />
            <RecordingOverviewDisclosure />
            <RecordingCommentsList sessionId={sessionRecordingId} />
            {debugMode && watchDebugDock === 'bottom' && <RecordingDebugSection />}
            {vision && dataProcessingAccepted && <RecordingObservationsSection sessionId={sessionRecordingId} />}
        </div>
    )
}
