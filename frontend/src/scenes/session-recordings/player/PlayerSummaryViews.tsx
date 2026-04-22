import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { ReactNode, useEffect, useRef, useState } from 'react'
import { Transition } from 'react-transition-group'
import { ENTERED, ENTERING } from 'react-transition-group/Transition'
import useResizeObserver from 'use-resize-observer'

import {
    IconAIText,
    IconCheckCircle,
    IconCircleDashed,
    IconClock,
    IconX,
    IconCollapse,
    IconExpand,
    IconKeyboard,
    IconMagicWand,
    IconPlay,
    IconPointer,
    IconThumbsDown,
    IconThumbsUp,
    IconWarning,
} from '@posthog/icons'
import { LemonBanner, LemonDivider, LemonTag, LemonTextArea, Link, Tooltip } from '@posthog/lemon-ui'

import { SESSION_SUMMARY_FEEDBACK_SURVEY_ID } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import {
    SegmentMeta,
    SessionKeyAction,
    SessionSegment,
    SessionSegmentKeyActions,
    SessionSegmentOutcome,
    SessionSummaryContent,
    SummarizationProgress,
} from './player-meta/types'

function formatEventMetaInfo(event: SessionKeyAction): JSX.Element {
    return (
        <pre className="m-0 p-0 font-mono text-xs whitespace-pre">
            {`Event: ${event.event}
            Event type: ${event.event_type}
            Issues: ${
                [
                    event.abandonment && 'Abandonment',
                    event.confusion && 'Confusion',
                    event.exception && `Exception (${event.exception})`,
                ]
                    .filter(Boolean)
                    .join(', ') || 'None'
            }
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

const PHASE_ORDER = [
    'fetching_data',
    'preparing_video',
    'rendering_video',
    'uploading_to_gemini',
    'analyzing_segments',
    'consolidating',
    'generating_embeddings',
    'saving_summary',
    'tagging',
    'cleanup',
] as const

const PHASE_LABELS: Record<(typeof PHASE_ORDER)[number], string> = {
    fetching_data: 'Fetching session data',
    preparing_video: 'Preparing video',
    rendering_video: 'Rendering video',
    uploading_to_gemini: 'Uploading video for analysis',
    analyzing_segments: 'Analyzing video segments',
    consolidating: 'Consolidating analysis',
    generating_embeddings: 'Generating embeddings',
    saving_summary: 'Saving summary',
    tagging: 'Tagging session',
    cleanup: 'Cleaning up',
}

type PhaseStatus = 'done' | 'active' | 'pending'

function phaseStatusAt(phaseIndex: number, currentStep: number): PhaseStatus {
    if (phaseIndex < currentStep) {
        return 'done'
    }
    if (phaseIndex === currentStep) {
        return 'active'
    }
    return 'pending'
}

function PhaseStatusIcon({ status }: { status: PhaseStatus }): JSX.Element {
    if (status === 'done') {
        return <IconCheckCircle className="text-success text-base shrink-0" />
    }
    if (status === 'active') {
        return <Spinner className="text-base shrink-0" />
    }
    return <IconCircleDashed className="text-muted-alt text-base shrink-0" />
}

function useTick(intervalMs: number): void {
    const [, setTick] = useState(0)
    useEffect(() => {
        const id = setInterval(() => setTick((t) => t + 1), intervalMs)
        return () => clearInterval(id)
    }, [intervalMs])
}

// Rough time constants per phase in seconds. Used to drive an asymptotic
// fill for phases without real sub-progress so the bar actually moves.
// At elapsed = tau the bar is at ~63%; at 2*tau ~86%; at 3*tau ~95%.
const PHASE_TAU_S: Record<(typeof PHASE_ORDER)[number], number> = {
    fetching_data: 3,
    preparing_video: 2,
    rendering_video: 30,
    uploading_to_gemini: 6,
    analyzing_segments: 30,
    consolidating: 8,
    generating_embeddings: 4,
    saving_summary: 2,
    tagging: 4,
    cleanup: 2,
}

// Phases whose work scales with recording length — for these we grow tau so
// the asymptotic fill doesn't saturate before the real work finishes on long
// recordings. Phases with real sub-progress are excluded (their tau is unused).
const PHASE_TAU_SCALES_WITH_DURATION: Partial<Record<(typeof PHASE_ORDER)[number], boolean>> = {
    fetching_data: true,
    uploading_to_gemini: true,
    consolidating: true,
}

function phaseTauSeconds(phase: (typeof PHASE_ORDER)[number], sessionDurationMs: number | undefined): number {
    const base = PHASE_TAU_S[phase]
    if (!PHASE_TAU_SCALES_WITH_DURATION[phase] || !sessionDurationMs || sessionDurationMs <= 0) {
        return base
    }
    // Square-root scaling with a 1-minute baseline: 4min→2x, 16min→4x.
    const minutes = sessionDurationMs / 60_000
    return base * Math.max(1, Math.sqrt(minutes))
}

function asymptoticFillPercent(elapsedSeconds: number, tauSeconds: number): number {
    return (1 - Math.exp(-elapsedSeconds / tauSeconds)) * 100
}

function phaseElapsedSeconds(
    phaseIndex: number,
    status: PhaseStatus,
    startTimes: Record<number, number>,
    now: number
): number | undefined {
    const start = startTimes[phaseIndex]
    if (start == null) {
        return undefined
    }
    if (status === 'active') {
        return Math.max(0, Math.round((now - start) / 1000))
    }
    if (status === 'done') {
        const nextStart = startTimes[phaseIndex + 1]
        if (nextStart == null) {
            return undefined
        }
        return Math.max(0, Math.round((nextStart - start) / 1000))
    }
    return undefined
}

interface PhaseRowProps {
    label: string
    detail?: string | null
    status: PhaseStatus
    elapsedSeconds?: number
    subProgressPercent?: number
}

function PhaseRow({ label, detail, status, elapsedSeconds, subProgressPercent }: PhaseRowProps): JSX.Element {
    const barPercent = status === 'done' ? 100 : status === 'active' ? (subProgressPercent ?? 0) : 0
    return (
        <div className={clsx('flex flex-col gap-1', status === 'pending' && 'opacity-50')}>
            <div className="flex items-center gap-2 text-xs">
                <PhaseStatusIcon status={status} />
                <span className="truncate">
                    {label}
                    {detail ? <span className="text-muted-alt">&nbsp;({detail})</span> : null}
                </span>
                <span className="flex-1" />
                {elapsedSeconds !== undefined ? (
                    <span className="font-mono text-muted shrink-0">{elapsedSeconds}s</span>
                ) : null}
            </div>
            <div className="pl-6">
                <LemonProgress percent={barPercent} />
            </div>
        </div>
    )
}

export function SummarizationProgressView({
    progress,
    sessionDurationMs,
}: {
    progress: SummarizationProgress
    sessionDurationMs?: number
}): JSX.Element {
    useTick(1000)
    const startTimesRef = useRef<Record<number, number>>({})
    if (!(progress.step in startTimesRef.current)) {
        startTimesRef.current[progress.step] = Date.now()
    }
    const startTimes = startTimesRef.current
    const now = Date.now()

    const firstStart = startTimes[0]
    const totalElapsed = firstStart != null ? Math.max(0, Math.round((now - firstStart) / 1000)) : 0

    return (
        <div className="flex flex-col gap-3 py-1">
            <div className="flex items-center justify-between text-sm font-medium">
                <div className="flex items-center gap-2">
                    <IconMagicWand />
                    <span>Generating session summary</span>
                </div>
                <span className="font-mono text-xs text-muted">{totalElapsed}s</span>
            </div>
            <div className="flex flex-col gap-2">
                {PHASE_ORDER.map((phase, i) => {
                    const status = phaseStatusAt(i, progress.step)
                    const elapsed = phaseElapsedSeconds(i, status, startTimes, now)

                    let subProgressPercent: number | undefined
                    let detail: string | null = null
                    if (phase === 'rendering_video' && status === 'active' && progress.rasterizer?.frame_progress) {
                        const { frame, estimatedTotalFrames } = progress.rasterizer.frame_progress
                        if (estimatedTotalFrames > 0) {
                            subProgressPercent = Math.min((frame / estimatedTotalFrames) * 100, 100)
                            detail = `${frame} / ${estimatedTotalFrames} frames`
                        } else if (frame > 0) {
                            detail = `${frame} frames`
                        }
                    } else if (phase === 'analyzing_segments' && status === 'active' && progress.segments_total > 0) {
                        subProgressPercent = Math.min(
                            (progress.segments_completed / progress.segments_total) * 100,
                            100
                        )
                        detail = `${progress.segments_completed} / ${progress.segments_total} segments`
                    }

                    // Fall back to an asymptotic time-based fill so phases without real
                    // sub-progress still show visual motion instead of sitting at 0%.
                    if (status === 'active' && subProgressPercent === undefined && elapsed !== undefined) {
                        subProgressPercent = asymptoticFillPercent(elapsed, phaseTauSeconds(phase, sessionDurationMs))
                    }

                    return (
                        <PhaseRow
                            key={phase}
                            label={PHASE_LABELS[phase]}
                            detail={detail}
                            status={status}
                            elapsedSeconds={elapsed}
                            subProgressPercent={subProgressPercent}
                        />
                    )
                })}
            </div>
        </div>
    )
}

export function LoadingTimer({ operation }: { operation?: string }): JSX.Element {
    const [elapsedSeconds, setElapsedSeconds] = useState(0)
    const { isVisible: isPageVisible } = usePageVisibility()

    useEffect(() => {
        if (operation !== undefined) {
            setElapsedSeconds(0)
        }
    }, [operation])

    useEffect(() => {
        if (!isPageVisible) {
            return
        }

        const interval = setInterval(() => {
            setElapsedSeconds((prev) => prev + 1)
        }, 1000)

        return () => clearInterval(interval)
    }, [isPageVisible])

    return <span className="font-mono text-xs text-muted">{elapsedSeconds}s</span>
}

interface SessionSegmentCollapseProps {
    header: ReactNode
    content: ReactNode
    actionsPresent?: boolean
    className?: string
    isFailed?: boolean
}

function SessionSegmentCollapse({
    header,
    content,
    actionsPresent,
    className,
    isFailed,
}: SessionSegmentCollapseProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const { height: contentHeight, ref: contentRef } = useResizeObserver({ box: 'border-box' })

    return (
        <div className={clsx('LemonCollapse', className)}>
            <div className="LemonCollapsePanel" aria-expanded={isExpanded}>
                <LemonButton
                    fullWidth
                    className={clsx(
                        'LemonCollapsePanel__header hover:bg-primary-alt-highlight border-l-[5px]',
                        !actionsPresent && 'LemonCollapsePanel__header--disabled',
                        isFailed && 'border-l-danger'
                    )}
                    onClick={actionsPresent ? () => setIsExpanded(!isExpanded) : undefined}
                    icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                    size="medium"
                    disabled={!actionsPresent}
                >
                    {header}
                </LemonButton>
                <Transition in={isExpanded} timeout={200} mountOnEnter unmountOnExit>
                    {(status) => (
                        <div
                            className="LemonCollapsePanel__body"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={
                                status === ENTERING || status === ENTERED
                                    ? {
                                          height: contentHeight,
                                      }
                                    : undefined
                            }
                            aria-busy={status.endsWith('ing')}
                        >
                            <div className="LemonCollapsePanel__content" ref={contentRef}>
                                {content}
                            </div>
                        </div>
                    )}
                </Transition>
            </div>
        </div>
    )
}

function SegmentMetaTable({ meta }: SegmentMetaProps): JSX.Element | null {
    if (!meta) {
        return null
    }

    return (
        <div className="grid grid-cols-2 gap-2 text-xs mt-2">
            <div className="flex items-center gap-1">
                <IconKeyboard className={meta.key_action_count && meta.key_action_count > 0 ? 'text-success' : ''} />
                <span className="text-muted">Key actions:</span>
                {isValidMetaNumber(meta.key_action_count) && <span>{meta.key_action_count}</span>}
            </div>
            <div className="flex items-center gap-1">
                <IconWarning className={meta.failure_count && meta.failure_count > 0 ? 'text-danger' : ''} />
                <span className="text-muted">Issues:</span>
                {isValidMetaNumber(meta.failure_count) && <span>{meta.failure_count}</span>}
            </div>
            <div className="flex items-center gap-1">
                <IconClock />
                <span className="text-muted">Duration:</span>
                {isValidMetaNumber(meta.duration) && isValidMetaNumber(meta.duration_percentage) && (
                    <span>
                        {meta.duration === 0 ? (
                            <span className="text-muted">...</span>
                        ) : (
                            `${formatMsIntoTime(meta.duration * 1000)} (${(
                                (meta.duration_percentage || 0) * 100
                            ).toFixed(2)}%)`
                        )}
                    </span>
                )}
            </div>
            <div className="flex items-center gap-1">
                <IconPointer />
                <span className="text-muted">Events:</span>
                {isValidMetaNumber(meta.events_count) && isValidMetaNumber(meta.events_percentage) && (
                    <span>
                        {meta.events_count === 0 ? (
                            <span className="text-muted">...</span>
                        ) : (
                            `${meta.events_count} (${((meta.events_percentage || 0) * 100).toFixed(2)}%)`
                        )}
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

function getIssueTags(event: SessionKeyAction): JSX.Element[] {
    const tags: JSX.Element[] = []
    if (event.abandonment) {
        tags.push(
            <LemonTag key="abandonment" size="small" type="warning">
                abandoned
            </LemonTag>
        )
    }
    if (event.confusion) {
        tags.push(
            <LemonTag key="confusion" size="small" type="warning">
                confusion
            </LemonTag>
        )
    }
    if (event.exception) {
        tags.push(
            <LemonTag key="exception" size="small" type={event.exception === 'blocking' ? 'danger' : 'warning'}>
                {event.exception}
            </LemonTag>
        )
    }
    return tags
}

function SessionSegmentView({
    segment,
    segmentOutcome,
    keyActions,
    onSeekToTime,
}: SessionSegmentViewProps): JSX.Element {
    return (
        <div key={segment.name} className="mb-4">
            <SessionSegmentCollapse
                className="cursor-pointer"
                actionsPresent={keyActions && keyActions.length > 0}
                isFailed={segmentOutcome && Object.keys(segmentOutcome).length > 0 && segmentOutcome.success === false}
                header={
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
                }
                content={
                    <>
                        {keyActions && keyActions.length > 0 ? (
                            <>
                                {keyActions?.map((segmentKeyActions) => (
                                    <SessionSummaryKeyActions
                                        key={segmentKeyActions.segment_index}
                                        keyActions={segmentKeyActions}
                                        segmentName={segment.name}
                                        onSeekToTime={onSeekToTime}
                                    />
                                ))}
                            </>
                        ) : (
                            <div className="text-muted-alt">
                                Waiting for key actions... <Spinner />
                            </div>
                        )}
                    </>
                }
            />
        </div>
    )
}

function SessionSummaryKeyActions({
    keyActions,
    segmentName,
    onSeekToTime,
}: {
    keyActions: SessionSegmentKeyActions
    segmentName?: string | null
    onSeekToTime: (time: number) => void
}): JSX.Element {
    const timeToSeekTo = (ms: number): number => Math.max(ms - 4000, 0)
    return (
        <>
            {keyActions.events?.map((event: SessionKeyAction, eventIndex: number, events: SessionKeyAction[]) =>
                isValidTimestamp(event.milliseconds_since_start) ? (
                    <div
                        key={`${segmentName}-${eventIndex}`}
                        className={clsx(
                            'py-2 px-2',
                            // Avoid adding a border to the last event
                            eventIndex !== events.length - 1 && 'border-b',
                            (event.abandonment || event.confusion || event.exception) && 'bg-danger-highlight'
                        )}
                    >
                        <div className="flex flex-row gap-2">
                            <div className="shrink-0 flex flex-col items-center gap-0.5 min-w-[4rem]">
                                <Tooltip title="Play from this moment">
                                    <button
                                        className="flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium text-primary-3000 hover:bg-primary-alt-highlight cursor-pointer border-0 bg-transparent"
                                        onClick={() => {
                                            onSeekToTime(timeToSeekTo(event.milliseconds_since_start!))
                                        }}
                                    >
                                        <IconPlay className="text-sm" />
                                        {formatMsIntoTime(event.milliseconds_since_start)}
                                    </button>
                                </Tooltip>
                                <div className="flex flex-row gap-1.5 pl-1.5">
                                    {event.current_url ? (
                                        <Tooltip title={event.current_url} placement="top">
                                            <span
                                                className="font-mono text-xs text-muted-alt cursor-pointer hover:text-primary-3000"
                                                onClick={() => {
                                                    void copyToClipboard(event.current_url || '', 'URL')
                                                }}
                                            >
                                                url
                                            </span>
                                        </Tooltip>
                                    ) : null}
                                    {event.event ? (
                                        <Tooltip title={formatEventMetaInfo(event)} placement="top">
                                            <span
                                                className="font-mono text-xs text-muted-alt cursor-pointer hover:text-primary-3000"
                                                onClick={() => {
                                                    const meta = `Event: ${event.event}\nEvent type: ${event.event_type}\nTimestamp: ${event.timestamp}${event.current_url ? `\nCurrent URL: ${event.current_url}` : ''}`
                                                    void copyToClipboard(meta, 'event metadata')
                                                }}
                                            >
                                                meta
                                            </span>
                                        </Tooltip>
                                    ) : null}
                                </div>
                            </div>

                            <div className="flex flex-col">
                                <div className="text-xs break-words">{event.description}</div>
                                <div className="flex flex-wrap gap-1 mt-2">
                                    {event.milliseconds_since_start === 0 && (
                                        <LemonTag size="small" type="default">
                                            before start
                                        </LemonTag>
                                    )}
                                    {getIssueTags(event).map((tag, i) => (
                                        <React.Fragment key={i}>{tag}</React.Fragment>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                ) : null
            )}
        </>
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

function SessionSummaryRoot({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex flex-col">{children}</div>
}

function SessionSummaryTitle(): JSX.Element {
    return (
        <h3 className="text-lg font-semibold mt-2 flex items-center gap-2">
            <IconAIText />
            AI summary
            <LemonTag type="warning" size="medium">
                BETA
            </LemonTag>
        </h3>
    )
}

function SessionSummarySubtitle({ sessionId }: { sessionId: string }): JSX.Element {
    return (
        <div className="flex align-center text-md gap-1">
            <p className="text-md ">Session ID: </p>
            <Tooltip title="View recording">
                <Link to={urls.replaySingle(sessionId)} target="_new">
                    {sessionId}
                </Link>
            </Tooltip>
        </div>
    )
}

function SessionSummaryOutcomeBanner({ sessionSummary }: { sessionSummary: SessionSummaryContent }): JSX.Element {
    return (
        <LemonBanner type={sessionSummary?.session_outcome?.success ? 'success' : 'error'} className="mb-4">
            <div className="text-sm font-normal">
                <strong>Session outcome:</strong> {sessionSummary?.session_outcome?.description}
            </div>
        </LemonBanner>
    )
}

function SessionSummarySegments({ sessionSummary }: { sessionSummary: SessionSummaryContent }): JSX.Element | null {
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)

    if (!sessionSummary?.segments) {
        return null
    }

    return (
        <div>
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
        </div>
    )
}

function SessionSummaryFeedbackSurvey(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setShowFeedbackSurvey } = useActions(playerMetaLogic(logicProps))

    const [survey, setSurvey] = useState<{ questions: any[] } | null>(null)
    const [openText, setOpenText] = useState('')
    const [submitted, setSubmitted] = useState(false)

    useEffect(() => {
        posthog.getSurveys((surveys: any[]) => {
            const match = surveys.find((s: any) => s.id === SESSION_SUMMARY_FEEDBACK_SURVEY_ID)
            if (match) {
                posthog.capture('survey shown', { $survey_id: SESSION_SUMMARY_FEEDBACK_SURVEY_ID })
                setSurvey(match)
            }
        })
    }, [])

    const trimmedText = openText.trim()

    const handleSubmit = (): void => {
        posthog.capture('survey sent', {
            $survey_id: SESSION_SUMMARY_FEEDBACK_SURVEY_ID,
            $survey_response: trimmedText,
        })
        setSubmitted(true)
        setTimeout(() => setShowFeedbackSurvey(false), 3000)
    }

    if (!survey) {
        return null
    }

    const question = survey.questions[0]

    return (
        <div className="border rounded p-3 mt-3">
            <div className="flex items-start justify-between">
                <strong className="text-sm">{question?.question}</strong>
                <LemonButton size="xsmall" icon={<IconX />} onClick={() => setShowFeedbackSurvey(false)} />
            </div>
            {submitted ? (
                <p className="text-sm text-muted mt-2">Thanks for your feedback!</p>
            ) : (
                <>
                    <LemonTextArea
                        placeholder="Share your feedback..."
                        value={openText}
                        onChange={setOpenText}
                        className="mt-2"
                        data-attr="session-summary-feedback-open-text"
                    />
                    <LemonButton
                        type="primary"
                        size="small"
                        className="mt-2"
                        disabledReason={!trimmedText ? 'Please enter your feedback' : undefined}
                        onClick={handleSubmit}
                        data-attr="session-summary-feedback-submit"
                    >
                        {question?.buttonText ?? 'Submit'}
                    </LemonButton>
                </>
            )}
        </div>
    )
}

function SessionSummaryFeedback(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { summaryHasHadFeedback, showFeedbackSurvey } = useValues(playerMetaLogic(logicProps))
    const { sessionSummaryFeedback, setShowFeedbackSurvey } = useActions(playerMetaLogic(logicProps))

    return (
        <div className="mb-2 mt-4">
            <div className="text-right">
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
                            setShowFeedbackSurvey(true)
                        }}
                    />
                </div>
            </div>
            {showFeedbackSurvey && SESSION_SUMMARY_FEEDBACK_SURVEY_ID && <SessionSummaryFeedbackSurvey />}
        </div>
    )
}

export const SessionSummaryComponent = {
    Root: SessionSummaryRoot,
    Title: SessionSummaryTitle,
    OutcomeBanner: SessionSummaryOutcomeBanner,
    LoadingState: SessionSummaryLoadingState,
    Segments: SessionSummarySegments,
    Feedback: SessionSummaryFeedback,
    Subtitle: SessionSummarySubtitle,
}

export function SessionSummary(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummary } = useValues(playerMetaLogic(logicProps))

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
        <SessionSummaryComponent.Root>
            {sessionSummary ? (
                <>
                    <SessionSummaryComponent.Title />

                    <div className="mb-2">
                        {sessionSummaryLoadingState.finished &&
                        sessionSummary?.session_outcome &&
                        sessionSummary.session_outcome.success !== null &&
                        sessionSummary.session_outcome.success !== undefined &&
                        sessionSummary.session_outcome.description ? (
                            <SessionSummaryComponent.OutcomeBanner sessionSummary={sessionSummary} />
                        ) : (
                            <div className="mb-4">
                                <SessionSummaryComponent.LoadingState
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
                    <SessionSummaryComponent.Segments sessionSummary={sessionSummary} />
                    <SessionSummaryComponent.Feedback />
                </>
            ) : (
                <div className="text-center text-muted-alt">No summary available for this session</div>
            )}
        </SessionSummaryComponent.Root>
    )
}
