import { useValues } from 'kea'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { SummarizeRecordingBar } from 'products/replay_vision/frontend/components/SummarizeRecordingBar'
import { visionSurfaceShown } from 'products/replay_vision/frontend/utils/visionSurface'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { MomentTicker } from './MomentTicker'
import { RecordingCommentsList } from './RecordingCommentsList'
import { RecordingDebugSection } from './RecordingDebugSection'
import { RecordingOverviewDisclosure } from './RecordingOverviewDisclosure'
import { RecordingSections } from './RecordingSections'
import { RecordingTitleBlock } from './RecordingTitleBlock'

/** Everything under the player in the watch layout: title, overview, comments, the inspector in Debug, then the rest. */
export function WatchPanel({
    summaryActions,
}: {
    /** Recording actions the host places beside the summarize button. */
    summaryActions?: React.ReactNode
}): JSX.Element | null {
    const { logicProps, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { sidebarOpen } = useValues(playerSettingsLogic)
    if (!sessionRecordingId) {
        return null
    }
    const vision = visionSurfaceShown(logicProps)

    return (
        <div className="flex flex-col gap-4 px-1 pt-3 pb-6" data-attr="watch-panel">
            {vision && <MomentTicker sessionId={sessionRecordingId} />}
            <RecordingTitleBlock />
            {vision && <SummarizeRecordingBar extraActions={summaryActions} />}
            <RecordingOverviewDisclosure />
            <RecordingCommentsList sessionId={sessionRecordingId} />
            {sidebarOpen && <RecordingDebugSection />}
            <RecordingSections />
        </div>
    )
}
