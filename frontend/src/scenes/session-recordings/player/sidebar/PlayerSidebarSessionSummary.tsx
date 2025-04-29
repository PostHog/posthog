import {
    IconAIText,
    IconClock,
    IconKeyboard,
    IconMagicWand,
    IconPointer,
    IconThumbsDown,
    IconThumbsUp,
    IconWarning,
} from '@posthog/icons'
import { LemonBanner, LemonCollapse, LemonDivider, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useEffect, useState } from 'react'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import {
    SegmentMeta,
    SessionKeyAction,
    SessionSegment,
    SessionSegmentKeyActions,
    SessionSegmentOutcome,
} from '../player-meta/types'

function formatEventMetaInfo(event: SessionKeyAction): JSX.Element {
    return (
        <pre className="m-0 p-0 font-mono text-xs whitespace-pre">
            {`Event: ${event.event}
            Event type: ${event.event_type}
            Failure: ${event.failure ? 'Yes' : 'No'}
            Timestamp: ${event.timestamp}
            Milliseconds since start: ${event.milliseconds_since_start}
            Window ID: ${event.window_id}
            Current URL: ${event.current_url}`}
        </pre>
    )
}

function formatMsIntoTime(ms: number): string {
    const seconds = Math.floor(ms / 1000)
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const remainingSeconds = seconds % 60

    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${remainingSeconds
        .toString()
        .padStart(2, '0')}`
}

const isValidTimestamp = (ms: unknown): ms is number => typeof ms === 'number' && !isNaN(ms) && ms >= 0
const isValidMetaNumber = (value: unknown): value is number => typeof value === 'number' && !isNaN(value) && value >= 0

interface SegmentMetaProps {
    meta: SegmentMeta | null | undefined
}

function LoadingTimer({ operation }: { operation?: string }): JSX.Element {
    const [elapsedSeconds, setElapsedSeconds] = useState(0)

    useEffect(() => {
        if (operation !== undefined) {
            setElapsedSeconds(0) // Reset timer only when operation changes and is provided
        }
    }, [operation])

    useEffect(() => {
        const interval = setInterval(() => {
            setElapsedSeconds((prev) => prev + 1)
        }, 1000)

        return () => clearInterval(interval)
    }, []) // Keep this dependency array empty to avoid resetting interval

    return <span className="font-mono text-xs text-muted">{elapsedSeconds}s</span>
}

function SegmentMetaTable({ meta }: SegmentMetaProps): JSX.Element | null {
    if (!meta) {
        return null
    }

    return (
        <div className="grid grid-cols-2 gap-2 text-xs mt-2">
            <div className="flex items-center gap-1">
                <IconKeyboard />
                <span className="text-muted">Key actions:</span>
                {isValidMetaNumber(meta.key_action_count) && <span>{meta.key_action_count}</span>}
            </div>
            <div className="flex items-center gap-1">
                <IconWarning className={meta.failure_count && meta.failure_count > 0 ? 'text-danger' : ''} />
                <span className="text-muted">Failures:</span>
                {isValidMetaNumber(meta.failure_count) && <span>{meta.failure_count}</span>}
            </div>
            <div className="flex items-center gap-1">
                <IconClock />
                <span className="text-muted">Duration:</span>
                {isValidMetaNumber(meta.duration) && isValidMetaNumber(meta.duration_percentage) && (
                    <span>
                        {formatMsIntoTime(meta.duration * 1000 || 0)} (
                        {((meta.duration_percentage || 0) * 100).toFixed(2)}%)
                    </span>
                )}
            </div>
            <div className="flex items-center gap-1">
                <IconPointer />
                <span className="text-muted">Events:</span>
                {isValidMetaNumber(meta.events_count) && isValidMetaNumber(meta.events_percentage) && (
                    <span>
                        {meta.events_count} ({((meta.events_percentage || 0) * 100).toFixed(2)}%)
                    </span>
                )}
            </div>
        </div>
    )
}

interface SessionSegmentViewProps {
    segment: SessionSegment
    segmentOutcome: SessionSegmentOutcome | undefined
    keyActions: SessionSegmentKeyActions[]
    onSeekToTime: (time: number) => void
}

function SessionSegmentView({
    segment,
    segmentOutcome,
    keyActions,
    onSeekToTime,
}: SessionSegmentViewProps): JSX.Element {
    return (
        <div key={segment.name} className="mb-4">
            <LemonCollapse
                size="medium"
                className={`border-b cursor-pointer py-2 px-2 hover:bg-primary-alt-highlight ${
                    segmentOutcome && Object.keys(segmentOutcome).length > 0 && segmentOutcome.success === false
                        ? 'bg-danger-highlight'
                        : ''
                }`}
                panels={[
                    {
                        key: 'previous',
                        header: (
                            <div className="py-2">
                                <div className="flex flex-row gap-2">
                                    <h3 className="mb-1">{segment.name}</h3>
                                    {segmentOutcome && Object.keys(segmentOutcome).length > 0 ? (
                                        <div>
                                            {segmentOutcome.success ? null : (
                                                <LemonTag size="small" type="default">
                                                    failed
                                                </LemonTag>
                                            )}
                                        </div>
                                    ) : (
                                        <Spinner />
                                    )}
                                </div>
                                {segmentOutcome && (
                                    <>
                                        <p className="text-sm font-normal mb-0">{segmentOutcome.summary}</p>
                                    </>
                                )}
                                <SegmentMetaTable
                                    meta={segment.meta && Object.keys(segment.meta).length > 0 ? segment.meta : null}
                                />
                            </div>
                        ),
                        content: (
                            <>
                                {keyActions?.map((keyAction) =>
                                    keyAction.events?.map((event: SessionKeyAction, eventIndex: number) =>
                                        isValidTimestamp(event.milliseconds_since_start) ? (
                                            <div
                                                key={`${segment.name}-${eventIndex}`}
                                                className={`border-b cursor-pointer py-2 px-2 hover:bg-primary-alt-highlight ${
                                                    event.failure ? 'bg-danger-highlight' : ''
                                                }`}
                                                onClick={() => {
                                                    if (!isValidTimestamp(event.milliseconds_since_start)) {
                                                        return
                                                    }
                                                    onSeekToTime(event.milliseconds_since_start)
                                                }}
                                            >
                                                <div className="flex flex-row gap-2">
                                                    <span className="text-muted-alt shrink-0 min-w-[4rem] font-mono text-xs">
                                                        {formatMsIntoTime(event.milliseconds_since_start)}
                                                        <div className="flex flex-row gap-2 mt-1">
                                                            {event.current_url ? (
                                                                <Link to={event.current_url} target="_blank">
                                                                    <Tooltip title={event.current_url} placement="top">
                                                                        <span className="font-mono text-xs text-muted-alt">
                                                                            url
                                                                        </span>
                                                                    </Tooltip>
                                                                </Link>
                                                            ) : null}
                                                            <Tooltip title={formatEventMetaInfo(event)} placement="top">
                                                                <span className="font-mono text-xs text-muted-alt">
                                                                    meta
                                                                </span>
                                                            </Tooltip>
                                                        </div>
                                                    </span>

                                                    <span className="text-xs break-words">{event.description}</span>
                                                </div>
                                            </div>
                                        ) : null
                                    )
                                )}
                            </>
                        ),
                    },
                ]}
            />
        </div>
    )
}

interface SessionSummaryLoadingStateProps {
    finished: boolean
    operation?: string
    counter?: number
    name?: string
    outOf?: number
}

function SessionSummaryLoadingState({ operation, counter, name, outOf }: SessionSummaryLoadingStateProps): JSX.Element {
    return (
        <div className="mb-4 grid grid-cols-[auto_1fr] gap-x-2">
            <Spinner className="text-2xl row-span-2 self-center" />
            <div className="flex items-center justify-between">
                <span className="text-muted">
                    {operation}&nbsp;
                    {counter !== undefined && (
                        <span className="font-semibold">
                            ({counter}
                            {outOf ? ` out of ${outOf}` : ''})
                        </span>
                    )}
                    {name ? ':' : ''}
                </span>
                <div className="flex items-center gap-1 ml-auto font-mono text-xs">
                    <LoadingTimer operation={operation} />
                </div>
            </div>
            {name ? (
                <div className="font-semibold">{name}</div>
            ) : (
                // Empty div to maintain two rows for spinner alignment
                <div />
            )}
        </div>
    )
}

function SessionSummary(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { sessionSummary, summaryHasHadFeedback } = useValues(playerMetaLogic(logicProps))
    const { sessionSummaryFeedback } = useActions(playerMetaLogic(logicProps))

    const getSessionSummaryLoadingState = (): SessionSummaryLoadingStateProps => {
        if (!sessionSummary) {
            return {
                finished: false,
                operation: 'Researching the session...',
            }
        }
        const segments = sessionSummary.segments || []
        const hasSegmentsWithKeyActions = segments.some((segment) =>
            sessionSummary.key_actions?.some(
                (keyAction) => keyAction.segment_index === segment.index && keyAction.events?.length
            )
        )
        const hasSegmentsWithOutcomes = segments.some((segment) =>
            sessionSummary.segment_outcomes?.some((outcome) => outcome.segment_index === segment.index)
        )
        const allSegmentsHaveSuccess = segments.every((segment) =>
            sessionSummary.segment_outcomes?.some(
                (outcome) =>
                    outcome.segment_index === segment.index && outcome.success !== null && outcome.success !== undefined
            )
        )
        // If all segments have a success outcome, it means the data is fully loaded and loading state can be hidden
        if (allSegmentsHaveSuccess) {
            return {
                finished: true,
            }
        }
        // If some segments have outcomes already, it means we stream the success and summary of each segment
        if (hasSegmentsWithOutcomes) {
            return {
                finished: false,
                operation: 'Analyzing the success of each segment',
            }
        }
        // If some segments have key actions already, it means we stream the key actions for each segment
        if (hasSegmentsWithKeyActions) {
            // Find first segment that has no key actions
            const nextSegmentIndex = segments.findIndex(
                (segment) =>
                    !sessionSummary.key_actions?.some(
                        (keyAction) => keyAction.segment_index === segment.index && keyAction.events?.length
                    )
            )
            // If we found such segment, and it's the first one, take it as current
            // If we don't find such segment, it means we are researching the last segment
            let currentSegmentIndex
            if (nextSegmentIndex === 0) {
                currentSegmentIndex = 0
            } else if (nextSegmentIndex === -1) {
                currentSegmentIndex = segments.length - 1
            } else {
                currentSegmentIndex = nextSegmentIndex - 1
            }
            const currentSegment = segments[currentSegmentIndex]
            return {
                finished: false,
                operation: 'Researching key actions for segments',
                counter: currentSegmentIndex,
                name: currentSegment?.name ?? undefined,
                outOf: segments.length,
            }
        }
        // If no segments have key actions or outcomes, it means we are researching the segments for the session
        return {
            finished: false,
            operation: 'Researching segments for the session...',
            counter: segments.length || undefined,
        }
    }

    const sessionSummaryLoadingState = getSessionSummaryLoadingState()

    return (
        <div className="flex flex-col">
            {sessionSummary ? (
                <>
                    <h3 className="text-lg font-semibold mb-4 mt-2 flex items-center gap-2">
                        <IconAIText />
                        AI Replay Research
                        <LemonTag type="completion" size="medium">
                            ALPHA
                        </LemonTag>
                    </h3>

                    <div className="mb-2">
                        {sessionSummaryLoadingState.finished &&
                        sessionSummary?.session_outcome &&
                        sessionSummary.session_outcome.success !== null &&
                        sessionSummary.session_outcome.success !== undefined &&
                        sessionSummary.session_outcome.description ? (
                            <LemonBanner
                                type={sessionSummary.session_outcome.success ? 'success' : 'error'}
                                className="mb-4"
                            >
                                <div className="text-sm font-normal">
                                    <div>{sessionSummary.session_outcome.description}</div>
                                </div>
                            </LemonBanner>
                        ) : (
                            <div className="mb-4">
                                <SessionSummaryLoadingState
                                    finished={sessionSummaryLoadingState.finished}
                                    operation={sessionSummaryLoadingState.operation}
                                    counter={sessionSummaryLoadingState.counter}
                                    name={sessionSummaryLoadingState.name}
                                    outOf={sessionSummaryLoadingState.outOf}
                                />
                            </div>
                        )}
                        <LemonDivider />
                    </div>
                    {sessionSummary?.segments?.map((segment) => {
                        const matchingSegmentOutcome = sessionSummary?.segment_outcomes?.find(
                            (outcome) => outcome.segment_index === segment.index
                        )
                        const matchingKeyActions = sessionSummary?.key_actions?.filter(
                            (keyAction) => keyAction.segment_index === segment.index
                        )
                        return (
                            <SessionSegmentView
                                key={segment.name}
                                segment={segment}
                                segmentOutcome={matchingSegmentOutcome}
                                keyActions={matchingKeyActions || []}
                                onSeekToTime={seekToTime}
                            />
                        )
                    })}

                    <div className="text-right mb-2 mt-4">
                        <p>Is this a good summary?</p>
                        <div className="flex flex-row gap-2 justify-end">
                            <LemonButton
                                size="xsmall"
                                type="primary"
                                icon={<IconThumbsUp />}
                                disabledReason={summaryHasHadFeedback ? 'Thanks for your feedback!' : undefined}
                                onClick={() => {
                                    sessionSummaryFeedback('good')
                                }}
                            />
                            <LemonButton
                                size="xsmall"
                                type="primary"
                                icon={<IconThumbsDown />}
                                disabledReason={summaryHasHadFeedback ? 'Thanks for your feedback!' : undefined}
                                onClick={() => {
                                    sessionSummaryFeedback('bad')
                                }}
                            />
                        </div>
                    </div>
                </>
            ) : (
                <div className="text-center text-muted-alt">No summary available for this session</div>
            )}
        </div>
    )
}

function LoadSessionSummaryButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummaryLoading } = useValues(playerMetaLogic(logicProps))
    const { summarizeSession } = useActions(playerMetaLogic(logicProps))

    return (
        <LemonButton
            size="small"
            type="primary"
            icon={<IconMagicWand />}
            fullWidth={true}
            data-attr="load-session-summary"
            disabledReason={sessionSummaryLoading ? 'Loading...' : undefined}
            onClick={summarizeSession}
        >
            Use AI to summarise this session
        </LemonButton>
    )
}

export function PlayerSidebarSessionSummary(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummary, sessionSummaryLoading } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="rounded border bg-surface-primary px-2 py-1">
            {sessionSummaryLoading ? (
                <>
                    <div className="flex items-center justify-between">
                        <div>
                            Researching the session... <Spinner />
                        </div>
                        <div className="flex items-center gap-1 ml-auto">
                            <LoadingTimer />
                        </div>
                    </div>
                </>
            ) : sessionSummary ? (
                <SessionSummary />
            ) : (
                <LoadSessionSummaryButton />
            )}
        </div>
    )
}
