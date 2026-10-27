import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

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

import { ReplayListPicksMode, ReplayListSegment, replayListColumnLogic } from './replayListColumnLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { usePlayerMounted } from './usePlayerMounted'

export interface ReplayListColumnProps {
    logicKey: string
    recordingsList: ReactNode
    /** The What to watch list, when the picks experiment offers one. */
    picksList?: ReactNode
    picksMode: ReplayListPicksMode
    unwatchedPicksCount?: number
    onPicksSelected?: (selected: boolean) => void
}

export function ReplayListColumn(props: ReplayListColumnProps): JSX.Element {
    const { activeSessionRecording } = useValues(sessionRecordingsPlaylistLogic)
    return activeSessionRecording ? (
        <ReplayListColumnForRecording {...props} recording={activeSessionRecording} />
    ) : (
        <ReplayListColumnView {...props} recording={null} momentsAvailable={null} />
    )
}

/** Scans shows once the recording has an observation or a summary on the way, so an empty pane never opens. */
function ReplayListColumnForRecording({
    recording,
    ...props
}: ReplayListColumnProps & { recording: SessionRecordingType }): JSX.Element {
    const { observations, summarizePending, hasLoadedObservations } = useValues(
        observationsDockLogic({ sessionId: recording.id })
    )
    const momentsAvailable = observations.length > 0 || summarizePending ? true : hasLoadedObservations ? false : null
    return <ReplayListColumnView {...props} recording={recording} momentsAvailable={momentsAvailable} />
}

function ReplayListColumnView({
    logicKey,
    recordingsList,
    picksList,
    picksMode,
    unwatchedPicksCount = 0,
    onPicksSelected,
    recording,
    momentsAvailable,
}: ReplayListColumnProps & { recording: SessionRecordingType | null; momentsAvailable: boolean | null }): JSX.Element {
    const logic = replayListColumnLogic({ logicKey })
    const { effectiveSegmentFor } = useValues(logic)
    const { setSegment, settleSegment } = useActions(logic)

    const playerLogicProps: SessionRecordingPlayerLogicProps | null = recording
        ? { playerKey: logicKey, sessionRecordingId: recording.id, watchLayout: true }
        : null
    const segment = effectiveSegmentFor(picksMode, momentsAvailable)
    useEffect(() => {
        settleSegment(picksMode, momentsAvailable)
    }, [picksMode, momentsAvailable, settleSegment])

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
            label: picksList && momentsAvailable ? 'All' : 'All recordings',
            'data-attr': 'list-segment-recordings',
        },
        ...(momentsAvailable && playerLogicProps
            ? [
                  {
                      value: 'moments' as const,
                      label: (
                          <span className="flex items-center gap-1">
                              <IconSparkles />
                              <span>Scans</span>
                              <MomentsBadge sessionId={playerLogicProps.sessionRecordingId} />
                          </span>
                      ),
                      'data-attr': 'list-segment-moments',
                  },
              ]
            : []),
    ]

    return (
        <div className="flex flex-col h-full min-h-0">
            {options.length > 1 && (
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
            )}
            <div className="flex flex-col flex-1 min-h-0">
                {segment === 'picks' ? (
                    picksList
                ) : segment === 'moments' && playerLogicProps && recording ? (
                    <MomentsSegment
                        key={recording.id}
                        playerLogicProps={playerLogicProps}
                        personDisplay={asDisplay(recording.person)}
                        person={recording.person}
                        durationSeconds={recording.recording_duration}
                    />
                ) : (
                    recordingsList
                )}
            </div>
        </div>
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
        return <p className="text-muted text-sm p-4 m-0">Open a recording to see its scans.</p>
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
