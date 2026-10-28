import { useValues } from 'kea'

import { IconChevronRight, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { colonDelimitedDuration } from 'lib/utils/durations'
import { replayListColumnLogic } from 'scenes/session-recordings/playlist/replayListColumnLogic'

import { observationsDockLogic } from 'products/replay_vision/frontend/logics/observationsDockLogic'
import {
    momentCount,
    surroundingMoments,
    timelineMoments,
} from 'products/replay_vision/frontend/utils/recordingTimeline'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

const formatMs = (ms: number): string => colonDelimitedDuration(ms / 1000, ms >= 3_600_000 ? 3 : 2)

export function MomentTicker({ sessionId }: { sessionId: string }): JSX.Element | null {
    const { timeline } = useValues(observationsDockLogic({ sessionId }))
    const { logicProps, currentPlayerTime } = useValues(sessionRecordingPlayerLogic)
    const moments = timelineMoments(timeline)
    if (moments.length === 0) {
        return null
    }
    const { current, next } = surroundingMoments(moments, currentPlayerTime)
    const seek = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }

    return (
        <div className="flex items-center gap-1 flex-wrap text-xs" data-attr="moment-ticker">
            {current && (
                <LemonButton
                    size="xsmall"
                    onClick={() => seek(current.atMs)}
                    data-attr="moment-ticker-current"
                    className="max-w-full"
                >
                    <span className="truncate">
                        <span className="text-secondary tabular-nums">{formatMs(current.atMs)}</span>{' '}
                        <span>{current.label}</span>
                    </span>
                </LemonButton>
            )}
            {next && (
                <LemonButton
                    size="xsmall"
                    sideIcon={<IconChevronRight />}
                    onClick={() => seek(next.atMs)}
                    data-attr="moment-ticker-next"
                    className="max-w-full"
                >
                    <span className="truncate">
                        <span className="text-secondary">next</span>{' '}
                        <span className="text-secondary tabular-nums">{formatMs(next.atMs)}</span>{' '}
                        <span>{next.label}</span>
                    </span>
                </LemonButton>
            )}
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconSparkles />}
                className="ml-auto"
                onClick={() =>
                    replayListColumnLogic.findMounted({ logicKey: logicProps.playerKey })?.actions.setSegment('moments')
                }
                data-attr="moment-ticker-open-moments"
            >
                <span>{momentCount(timeline)}</span> moments
            </LemonButton>
        </div>
    )
}
