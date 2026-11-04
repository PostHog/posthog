import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Badge, Collapsible, CollapsibleContent, CollapsibleTrigger, Skeleton } from '@posthog/quill'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { RecordingMoments } from 'products/replay_vision/frontend/components/RecordingMoments'
import { RecordingObservationsEmptyState } from 'products/replay_vision/frontend/components/RecordingObservationsEmptyState'
import { observationsDockLogic } from 'products/replay_vision/frontend/logics/observationsDockLogic'
import { momentCount } from 'products/replay_vision/frontend/utils/recordingTimeline'
import { recordingScanBlock } from 'products/replay_vision/frontend/utils/scanEligibility'

export function RecordingObservationsSection({ sessionId }: { sessionId: string }): JSX.Element {
    const { logicProps, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { observations, hasLoadedObservations, timeline } = useValues(observationsDockLogic({ sessionId }))
    const { watchPanelOpenSections } = useValues(playerSettingsLogic)
    const { toggleWatchPanelSection } = useActions(playerSettingsLogic)
    const count = momentCount(timeline)

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
        <Collapsible
            data-quill
            open={watchPanelOpenSections.includes('observations')}
            onOpenChange={() => toggleWatchPanelSection('observations')}
            data-attr="watch-panel-section-observations"
        >
            <CollapsibleTrigger className="w-full">
                <IconSparkles />
                <span>Observations</span>
                {count > 0 && <Badge>{count}</Badge>}
                <span className="grow" />
            </CollapsibleTrigger>
            <CollapsibleContent className="p-0">{content}</CollapsibleContent>
        </Collapsible>
    )
}
