import { useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { QuillRecordingMoments } from 'products/replay_vision/frontend/components/QuillRecordingMoments'
import { QuillRecordingObservationsEmptyState } from 'products/replay_vision/frontend/components/QuillRecordingObservationsEmptyState'
import { observationsDockLogic } from 'products/replay_vision/frontend/logics/observationsDockLogic'
import { momentCount } from 'products/replay_vision/frontend/utils/recordingTimeline'
import { recordingScanBlock } from 'products/replay_vision/frontend/utils/scanEligibility'

import { WatchPanelSections } from './WatchPanelSections'

export function WatchPanelSectionsWithObservations({
    sessionId,
    debug,
}: {
    sessionId: string
    debug: boolean
}): JSX.Element {
    const { logicProps, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { observations, hasLoadedObservations, timeline } = useValues(observationsDockLogic({ sessionId }))

    const content = !hasLoadedObservations ? (
        <Skeleton className="h-24 m-2" />
    ) : observations.length === 0 ? (
        <QuillRecordingObservationsEmptyState
            sessionId={sessionId}
            scanBlock={recordingScanBlock(sessionPlayerMetaData)}
        />
    ) : (
        <div className="flex flex-col max-h-[60vh]">
            <QuillRecordingMoments key={sessionId} sessionId={sessionId} playerLogicProps={logicProps} />
        </div>
    )

    return (
        <WatchPanelSections
            debug={debug}
            observations={{ count: momentCount(timeline), hasObservations: observations.length > 0, content }}
        />
    )
}
