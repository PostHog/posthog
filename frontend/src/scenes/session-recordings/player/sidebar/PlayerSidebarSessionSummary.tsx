import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { ReactNode, useEffect, useState } from 'react'
import { Transition } from 'react-transition-group'
import { ENTERED, ENTERING } from 'react-transition-group/Transition'
import useResizeObserver from 'use-resize-observer'

import {
    IconAIText,
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
import { LemonBanner, LemonCheckbox, LemonDivider, LemonTag, LemonTextArea, Link, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS, SESSION_SUMMARY_FEEDBACK_SURVEY_ID } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { playerInspectorLogic } from '../inspector/playerInspectorLogic'
import {
    SegmentMeta,
    SessionKeyAction,
    SessionSegment,
    SessionSegmentKeyActions,
    SessionSegmentOutcome,
    SessionSummaryContent,
} from '../player-meta/types'

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

function LoadingTimer({ operation }: { operation?: string }): JSX.Element {
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
    const [selectedChoices, setSelectedChoices] = useState<string[]>([])
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

    const handleChoiceToggle = (choice: string, checked: boolean): void => {
        setSelectedChoices((prev) => (checked ? [...prev, choice] : prev.filter((c) => c !== choice)))
    }

    const handleSubmit = (): void => {
        const response = [...selectedChoices]
        if (openText) {
            response.push(openText)
        }
        posthog.capture('survey sent', {
            $survey_id: SESSION_SUMMARY_FEEDBACK_SURVEY_ID,
            $survey_response: response,
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
                    {question?.choices && (
                        <ul className="list-none mt-2 space-y-1">
                            {question.choices.map((choice: string, index: number) => {
                                if (index === question.choices.length - 1 && question.hasOpenChoice) {
                                    return (
                                        <LemonTextArea
                                            key={choice}
                                            placeholder="Any other feedback?"
                                            value={openText}
                                            onChange={setOpenText}
                                            className="mt-2"
                                            data-attr="session-summary-feedback-open-text"
                                        />
                                    )
                                }
                                return (
                                    <li key={choice}>
                                        <LemonCheckbox
                                            onChange={(checked) => handleChoiceToggle(choice, checked)}
                                            label={choice}
                                            className="font-normal"
                                            data-attr={`session-summary-feedback-choice-${index}`}
                                        />
                                    </li>
                                )
                            })}
                        </ul>
                    )}
                    <LemonButton
                        type="primary"
                        size="small"
                        className="mt-2"
                        disabledReason={
                            selectedChoices.length === 0 && !openText ? 'Please select at least one option' : undefined
                        }
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
    const { featureFlags } = useValues(featureFlagLogic)

    const showSurveyFlag = !!featureFlags[FEATURE_FLAGS.SHOW_SESSION_SUMMARY_FEEDBACK_SURVEY]

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
                            if (showSurveyFlag) {
                                setShowFeedbackSurvey(true)
                            }
                        }}
                    />
                </div>
            </div>
            {showSurveyFlag && showFeedbackSurvey && SESSION_SUMMARY_FEEDBACK_SURVEY_ID && (
                <SessionSummaryFeedbackSurvey />
            )}
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

function SessionSummary(): JSX.Element {
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

function LoadSessionSummaryButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummaryLoading, loading } = useValues(playerMetaLogic(logicProps))
    const inspectorLogic = playerInspectorLogic(logicProps)
    const { allItemsByMiniFilterKey } = useValues(inspectorLogic)
    const { summarizeSession } = useActions(playerMetaLogic(logicProps))

    // We need $autocapture events to be able to generate a summary
    const hasEvents = [
        'events-posthog',
        'events-custom',
        'events-pageview',
        'events-autocapture',
        'events-exceptions',
    ].some((key) => allItemsByMiniFilterKey[key]?.length > 0)
    const hasAutocaptureEvents = allItemsByMiniFilterKey['events-autocapture']?.length > 0

    return (
        <div className="space-y-2">
            <LemonButton
                size="small"
                type="primary"
                icon={<IconMagicWand />}
                fullWidth={true}
                data-attr="load-session-summary"
                disabled={loading || !hasAutocaptureEvents}
                disabledReason={sessionSummaryLoading ? 'Loading...' : undefined}
                onClick={summarizeSession}
            >
                Use AI to summarise this session
            </LemonButton>

            {loading ? (
                <div className="text-sm">
                    Checking on session events... <Spinner />
                </div>
            ) : (
                !hasAutocaptureEvents && (
                    <div>
                        {hasEvents ? (
                            <>
                                <h4>No autocapture events found for this session</h4>
                                <p className="text-sm mb-1">
                                    Please, ensure that Autocapture is enabled in project's settings, or try again in a
                                    few minutes.
                                </p>
                            </>
                        ) : (
                            <>
                                <h4>Session events are not available for summary yet</h4>
                                <p className="text-sm mb-1">Please, try again in a few minutes.</p>
                            </>
                        )}
                    </div>
                )
            )}
        </div>
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
