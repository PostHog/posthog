import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonBadge, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { colonDelimitedDuration } from 'lib/utils/durations'
import { SessionRecordingPlayerLogicProps } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { SessionRecordingType } from '~/types'

import { PersonIcon } from 'products/persons/frontend/components/PersonDisplay'
import { asDisplay } from 'products/persons/frontend/person-utils'
import { RecordingMoments } from 'products/replay_vision/frontend/components/RecordingMoments'
import { observationsDockLogic } from 'products/replay_vision/frontend/logics/observationsDockLogic'
import { momentCount } from 'products/replay_vision/frontend/utils/recordingTimeline'

import { ReplayListSegment, replayListColumnLogic } from './replayListColumnLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { usePlayerMounted } from './usePlayerMounted'

export interface ReplayListColumnProps {
    logicKey: string
    recordingsList: ReactNode
    /** The What to watch list, when the picks experiment offers one. */
    picksList?: ReactNode
    /** Where the picks logic would land a fresh page; null when picks are off. */
    picksMode: 'picks' | 'recordings' | null
    unwatchedPicksCount?: number
    onPicksSelected?: (selected: boolean) => void
}

/** The list column's segment switch: What to watch, All recordings, and the open recording's Moments. */
export function ReplayListColumn({
    logicKey,
    recordingsList,
    picksList,
    picksMode,
    unwatchedPicksCount = 0,
    onPicksSelected,
}: ReplayListColumnProps): JSX.Element {
    const logic = replayListColumnLogic({ logicKey })
    const { effectiveSegmentFor } = useValues(logic)
    const { setSegment } = useActions(logic)
    const { activeSessionRecording } = useValues(sessionRecordingsPlaylistLogic)

    const playerLogicProps: SessionRecordingPlayerLogicProps | null = activeSessionRecording
        ? { playerKey: logicKey, sessionRecordingId: activeSessionRecording.id }
        : null
    const segment = effectiveSegmentFor(picksMode, playerLogicProps !== null)

    const options = [
        ...(picksList
            ? [
                  {
                      value: 'picks' as const,
                      label: (
                          <span className="flex items-center gap-1">
                              <span>What to watch</span>
                              {unwatchedPicksCount > 0 && (
                                  <LemonBadge.Number count={unwatchedPicksCount} size="small" status="muted" />
                              )}
                          </span>
                      ),
                      'data-attr': 'list-segment-picks',
                  },
              ]
            : []),
        {
            value: 'recordings' as const,
            label: picksList ? 'All' : 'All recordings',
            'data-attr': 'list-segment-recordings',
        },
        {
            value: 'moments' as const,
            label: (
                <span className="flex items-center gap-1">
                    <IconSparkles />
                    <span>Moments</span>
                    {playerLogicProps && <MomentsBadge sessionId={playerLogicProps.sessionRecordingId} />}
                </span>
            ),
            disabledReason: playerLogicProps ? undefined : 'Open a recording to see its moments',
            'data-attr': 'list-segment-moments',
        },
    ]

    return (
        <>
            <LemonSegmentedButton
                size="small"
                fullWidth
                className="mb-2"
                value={segment}
                onChange={(next: ReplayListSegment) => {
                    setSegment(next)
                    if ((next === 'picks') !== (segment === 'picks')) {
                        onPicksSelected?.(next === 'picks')
                    }
                }}
                options={options}
            />
            {segment === 'picks' ? (
                picksList
            ) : segment === 'moments' && playerLogicProps && activeSessionRecording ? (
                <MomentsSegment
                    key={activeSessionRecording.id}
                    playerLogicProps={playerLogicProps}
                    personDisplay={asDisplay(activeSessionRecording.person)}
                    person={activeSessionRecording.person}
                    durationSeconds={activeSessionRecording.recording_duration}
                />
            ) : (
                recordingsList
            )}
        </>
    )
}

function MomentsBadge({ sessionId }: { sessionId: string }): JSX.Element | null {
    const { timeline } = useValues(observationsDockLogic({ sessionId }))
    const count = momentCount(timeline)
    return count > 0 ? <LemonBadge.Number count={count} size="small" status="muted" /> : null
}

function MomentsSegment({
    playerLogicProps,
    personDisplay,
    person,
    durationSeconds,
}: {
    playerLogicProps: SessionRecordingPlayerLogicProps
    personDisplay: string
    person: SessionRecordingType['person']
    durationSeconds: number | undefined
}): JSX.Element {
    const playerState = usePlayerMounted(playerLogicProps)
    if (playerState === 'waiting') {
        return (
            <div className="flex items-center gap-2 text-muted p-4">
                <Spinner /> Loading…
            </div>
        )
    }
    if (playerState === 'missing') {
        return <p className="text-muted text-sm p-4 m-0">Open a recording to see its moments.</p>
    }
    return (
        <div className="flex flex-col flex-1 min-h-0 border rounded bg-surface-primary overflow-hidden">
            <div className="flex items-center gap-2 px-2 py-1.5 border-b text-xs ph-no-capture">
                <PersonIcon person={person} size="sm" className="mr-0" />
                <span className="font-medium truncate flex-1">{personDisplay}</span>
                {durationSeconds !== undefined && (
                    <span className="text-secondary tabular-nums">{colonDelimitedDuration(durationSeconds)}</span>
                )}
            </div>
            <RecordingMoments sessionId={playerLogicProps.sessionRecordingId} playerLogicProps={playerLogicProps} />
        </div>
    )
}
