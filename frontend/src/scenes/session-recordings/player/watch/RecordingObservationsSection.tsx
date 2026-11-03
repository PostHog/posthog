import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBadge, LemonCollapse, LemonSkeleton } from '@posthog/lemon-ui'

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
        <LemonSkeleton className="h-24 m-2" />
    ) : observations.length === 0 ? (
        <RecordingObservationsEmptyState sessionId={sessionId} scanBlock={recordingScanBlock(sessionPlayerMetaData)} />
    ) : (
        <div className="flex flex-col max-h-[60vh]">
            <RecordingMoments key={sessionId} sessionId={sessionId} playerLogicProps={logicProps} />
        </div>
    )

    return (
        <LemonCollapse
            size="small"
            panels={[
                {
                    key: 'observations',
                    header: (
                        <span className="flex items-center gap-1.5">
                            <IconSparkles />
                            <span>Observations</span>
                            {count > 0 && <LemonBadge.Number count={count} size="small" status="muted" />}
                        </span>
                    ),
                    content,
                    className: 'p-0',
                    dataAttr: 'watch-panel-section-observations',
                },
            ]}
            activeKey={watchPanelOpenSections.includes('observations') ? 'observations' : null}
            onChange={() => toggleWatchPanelSection('observations')}
        />
    )
}
