import { useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { RecordingMoments } from 'products/replay_vision/frontend/components/RecordingMoments'
import { RecordingObservationsEmptyState } from 'products/replay_vision/frontend/components/RecordingObservationsEmptyState'
import { observationsDockLogic } from 'products/replay_vision/frontend/logics/observationsDockLogic'
import { momentCount } from 'products/replay_vision/frontend/utils/recordingTimeline'
import { recordingScanBlock } from 'products/replay_vision/frontend/utils/scanEligibility'

import { WatchPanelTabs } from './WatchPanelTabs'

export function WatchPanelTabsWithObservations({
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
        <RecordingObservationsEmptyState
            sessionId={sessionId}
            scanBlock={recordingScanBlock(sessionPlayerMetaData)}
            surface="watch"
        />
    ) : (
        <div className="flex flex-col max-h-[60vh]">
            <RecordingMoments key={sessionId} sessionId={sessionId} playerLogicProps={logicProps} />
        </div>
    )

    return (
        <WatchPanelTabs
            debug={debug}
            observations={{ count: momentCount(timeline), hasObservations: observations.length > 0, content }}
        />
    )
}
