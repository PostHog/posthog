import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { type Ref, Suspense, lazy, useEffect, useRef } from 'react'

import { IconWarning, IconWrench } from '@posthog/icons'
import { LemonButton, LemonDrawer, LemonTag, Spinner, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { LLMTrace } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LazyPersonAvatar } from './aiObservabilityColumnRenderers'
import { TraceSummary, aiObservabilitySessionDataLogic } from './aiObservabilitySessionDataLogic'
import { aiObservabilitySessionLogic } from './aiObservabilitySessionLogic'
import { buildSessionTimeline } from './buildSessionTimeline'
import { AIObservabilityTraceEvents } from './components/AIObservabilityTraceEvents'
import { SentimentBar } from './components/SentimentTag'
import { SessionPlayerControls } from './components/SessionPlayer/SessionPlayerControls'
import { SessionSeekbar } from './components/SessionPlayer/SessionSeekbar'
import { TypingIndicator } from './components/SessionPlayer/TypingIndicator'
import { TraceTimeline } from './components/TraceTimeline/TraceTimeline'
import { TranscriptBubbleStream } from './ConversationDisplay/TranscriptBubbleStream'
import { SessionTurn } from './extractSessionTurns'
import { llmSessionTitleLazyLoaderLogic } from './llmSessionTitleLazyLoaderLogic'
import { sessionPlaybackLogic } from './sessionPlaybackLogic'
import { formatLLMCost, getTraceTimestamp, sanitizeTraceUrlSearchParams } from './utils'

const LLMASessionFeedbackDisplay = lazy(() =>
    import('./LLMASessionFeedbackDisplay').then((m) => ({ default: m.LLMASessionFeedbackDisplay }))
)

type TurnPhase = 'userThinking' | 'aiThinking' | 'complete'

export const scene: SceneExport = {
    component: AIObservabilitySessionScene,
    logic: aiObservabilitySessionLogic,
}

export function AIObservabilitySessionScene(): JSX.Element {
    return <SessionDetailPanel showBreadcrumb />
}

export function SessionDetailPanel({ showBreadcrumb = false }: { showBreadcrumb?: boolean }): JSX.Element {
    const sessionLogic = aiObservabilitySessionLogic()
    const { sessionId, query } = useValues(sessionLogic)
    const sessionDataLogic = aiObservabilitySessionDataLogic({ sessionId, query })

    useAttachedLogic(sessionDataLogic, sessionLogic)

    return (
        <BindLogic logic={aiObservabilitySessionLogic} props={{}}>
            <BindLogic logic={aiObservabilitySessionDataLogic} props={{ sessionId, query }}>
                <SessionSceneWrapper showBreadcrumb={showBreadcrumb} />
            </BindLogic>
        </BindLogic>
    )
}

function SessionTraceSentimentBar({ sentiment }: { sentiment?: LLMTrace['sentiment'] }): JSX.Element | null {
    if (!sentiment) {
        return null
    }

    return (
        <div className="flex w-full justify-end">
            <div className="flex w-20 max-w-[75%] justify-end">
                <SentimentBar
                    label={sentiment.label ?? 'neutral'}
                    score={sentiment.score ?? 0}
                    messages={sentiment.messages}
                    size="full"
                />
            </div>
        </div>
    )
}

function SessionSceneWrapper({ showBreadcrumb = false }: { showBreadcrumb?: boolean }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const showFeedback = !!featureFlags[FEATURE_FLAGS.POSTHOG_AI_CONVERSATION_FEEDBACK_LLMA_SESSIONS]

    const {
        traces,
        initialLoading,
        responseError,
        sessionTurns,
        hasMoreData,
        nextDataLoading,
        summariesLoading,
        drawerTraceId,
        fullTraces,
        loadingFullTraces,
        expandedGenerationIds,
    } = useValues(aiObservabilitySessionDataLogic)
    const { sessionId, dateRange } = useValues(aiObservabilitySessionLogic)
    const { summarizeAllTraces, loadNextData, closeStepsDrawer, toggleGenerationExpanded, focusGenerationExpanded } =
        useActions(aiObservabilitySessionDataLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { getSessionTitle } = useValues(llmSessionTitleLazyLoaderLogic)
    const { ensureSessionTitleLoaded } = useActions(llmSessionTitleLazyLoaderLogic)
    // Computed once for the page, not per turn.
    const { searchParams } = useValues(router)
    const traceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })

    const drawerTurn = drawerTraceId ? sessionTurns.find((t) => t.trace.id === drawerTraceId) : undefined
    const drawerTraceUrl = drawerTurn
        ? combineUrl(urls.aiObservabilityTrace(drawerTurn.trace.id), {
              ...traceSearchParams,
              timestamp: getTraceTimestamp(drawerTurn.trace.createdAt),
          }).url
        : ''

    const playback = sessionPlaybackLogic({ sessionId })
    const { playing, speed, currentMs, durationMs } = useValues(playback)
    const { togglePlay, setSpeed, seek, setTimeline } = useActions(playback)
    const built = buildSessionTimeline(sessionTurns)
    // Keep the player's duration in sync with the computed timeline. A late full-trace
    // load can change a turn's latency (and the total duration) without changing the turn
    // count, so depend on the duration itself rather than the turn count — otherwise the
    // seekbar thumb (currentMs / durationMs) and the tick positions (built.durationMs)
    // drift apart. setTimeline clamps the position instead of rewinding, so re-syncing
    // mid-playback doesn't jump back to the start.
    useEffect(() => {
        setTimeline(built.durationMs)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sessionId, built.durationMs])

    // Idle: show the whole conversation. Scrubbing: reveal turns phase by phase.
    const isScrubbing = playing || currentMs > 0
    const revealedTurnCount = isScrubbing
        ? built.turnRevealsMs.reduce((n, revealMs) => (revealMs <= currentMs ? n + 1 : n), 0)
        : sessionTurns.length
    const phaseOf = (i: number): TurnPhase =>
        currentMs < built.turnStartsMs[i]
            ? 'userThinking'
            : currentMs < built.turnResponsesMs[i]
              ? 'aiThinking'
              : 'complete'

    // While playing, keep the newest turn in view above the docked player.
    const latestTurnRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (!playing || !latestTurnRef.current) {
            return
        }
        // Scroll fully to the bottom so the newest turn clears the sticky player.
        let scroller = latestTurnRef.current.parentElement
        while (scroller && scroller.scrollHeight <= scroller.clientHeight) {
            scroller = scroller.parentElement
        }
        if (scroller) {
            scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' })
        } else {
            latestTurnRef.current.scrollIntoView({ block: 'end', behavior: 'smooth' })
        }
    }, [playing, revealedTurnCount])

    const showSessionSummarization = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

    // Calculate session aggregates
    const sessionStats = traces.reduce(
        (acc, trace) => ({
            totalCost: acc.totalCost + (trace.totalCost || 0),
            totalLatency: acc.totalLatency + (trace.totalLatency || 0),
            traceCount: acc.traceCount + 1,
        }),
        { totalCost: 0, totalLatency: 0, traceCount: 0 }
    )

    // Same loader as the sessions list, time-bounded to the page's date range.
    const heroTitle = getSessionTitle(sessionId)
    const titleLoading = heroTitle === undefined
    // All traces in a session share the same user; show their avatar beside the title.
    const sessionDistinctId = traces[0]?.distinctId
    useEffect(() => {
        ensureSessionTitleLoaded(sessionId, dateRange ?? undefined)
    }, [sessionId, dateRange, ensureSessionTitleLoaded])

    if (initialLoading) {
        return <SpinnerOverlay />
    }
    if (responseError) {
        return <InsightErrorState />
    }
    if (!traces || traces.length === 0) {
        return <InsightEmptyState heading="No traces found" detail="This session has no traces." />
    }

    return (
        <div className="relative flex w-full flex-col gap-4 min-h-full">
            {showBreadcrumb && <SceneBreadcrumbBackButton />}
            <div className="flex items-center gap-2">
                {sessionDistinctId && <LazyPersonAvatar distinctId={sessionDistinctId} />}
                {titleLoading ? (
                    <LemonSkeleton className="h-8 w-96 max-w-full" />
                ) : (
                    heroTitle && <h1 className="text-2xl font-semibold leading-tight m-0 break-words">{heroTitle}</h1>
                )}
            </div>
            <header className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex gap-1.5 flex-wrap">
                    <LemonTag size="medium" className="bg-surface-primary">
                        <span className="font-mono">{sessionId}</span>
                    </LemonTag>
                    <LemonTag size="medium" className="bg-surface-primary">
                        {sessionStats.traceCount}
                        {hasMoreData ? '+' : ''} {sessionStats.traceCount === 1 ? 'trace' : 'traces'}
                    </LemonTag>
                    {sessionStats.totalCost > 0 && (
                        <LemonTag size="medium" className="bg-surface-primary">
                            Total: {formatLLMCost(sessionStats.totalCost)}
                        </LemonTag>
                    )}
                    {sessionStats.totalLatency > 0 && (
                        <LemonTag size="medium" className="bg-surface-primary">
                            {sessionStats.totalLatency.toFixed(2)}s
                        </LemonTag>
                    )}
                    {showFeedback && (
                        <Suspense fallback={<Spinner />}>
                            <LLMASessionFeedbackDisplay sessionId={sessionId} />
                        </Suspense>
                    )}
                </div>
                <SummarizeAllButton
                    loading={summariesLoading}
                    dataProcessingAccepted={dataProcessingAccepted}
                    onSummarize={summarizeAllTraces}
                />
            </header>

            <div className="flex flex-col flex-1">
                {(isScrubbing ? sessionTurns.slice(0, revealedTurnCount) : sessionTurns).map((turn, i, shown) => (
                    <SessionTurnView
                        key={turn.trace.id}
                        // Anchor for the player's auto-scroll: the last revealed turn.
                        rootRef={i === shown.length - 1 ? latestTurnRef : undefined}
                        turn={turn}
                        phase={isScrubbing ? phaseOf(i) : 'complete'}
                        showSentiment
                        showSessionSummarization={!!showSessionSummarization}
                        traceSearchParams={traceSearchParams}
                    />
                ))}
                {hasMoreData && (
                    <div className="flex justify-center pt-4">
                        <LemonButton
                            type="secondary"
                            loading={nextDataLoading}
                            onClick={loadNextData}
                            data-attr="llm-session-load-more-traces"
                        >
                            Load more traces
                        </LemonButton>
                    </div>
                )}
            </div>

            {/* Anchored to the bottom like a session-replay scrubber. */}
            {durationMs > 0 && (
                <div className="sticky bottom-0 z-10 mt-2 flex flex-col gap-2 rounded border border-primary bg-surface-primary p-3 shadow">
                    <SessionSeekbar
                        durationMs={durationMs}
                        currentMs={currentMs}
                        turnStartsMs={built.turnStartsMs}
                        turnResponsesMs={built.turnResponsesMs}
                        onSeek={seek}
                    />
                    <div className="flex items-center gap-3 text-[11px] text-muted">
                        <span className="flex items-center gap-1">
                            <span className="w-1 h-3 rounded-full bg-muted" /> User
                        </span>
                        <span className="flex items-center gap-1">
                            <span className="w-1 h-3 rounded-full bg-success" /> Assistant
                        </span>
                    </div>
                    <SessionPlayerControls
                        playing={playing}
                        speed={speed}
                        currentMs={currentMs}
                        durationMs={durationMs}
                        onTogglePlay={togglePlay}
                        onSetSpeed={setSpeed}
                    />
                </div>
            )}

            <LemonDrawer
                isOpen={!!drawerTraceId}
                onClose={closeStepsDrawer}
                title={drawerTurn?.trace.traceName || 'Trace steps'}
                width={960}
                data-attr="llm-session-steps-drawer"
                description={
                    drawerTraceUrl ? (
                        <Link to={drawerTraceUrl} target="_blank" className="text-xs">
                            Open full trace
                        </Link>
                    ) : undefined
                }
            >
                {drawerTraceId ? (
                    <div className="flex flex-col gap-3">
                        <TraceTimeline
                            events={fullTraces[drawerTraceId]?.events ?? []}
                            selectedEventId={
                                expandedGenerationIds.size === 1 ? Array.from(expandedGenerationIds)[0] : null
                            }
                            onSelectEvent={focusGenerationExpanded}
                        />
                        <AIObservabilityTraceEvents
                            trace={fullTraces[drawerTraceId]}
                            isLoading={loadingFullTraces.has(drawerTraceId)}
                            expandedEventIds={expandedGenerationIds}
                            onToggleEventExpand={toggleGenerationExpanded}
                        />
                    </div>
                ) : null}
            </LemonDrawer>
        </div>
    )
}

function SummarizeAllButton({
    loading,
    dataProcessingAccepted,
    onSummarize,
}: {
    loading: boolean
    dataProcessingAccepted: boolean
    onSummarize: () => void
}): JSX.Element {
    if (!dataProcessingAccepted) {
        return (
            <AIConsentPopoverWrapper showArrow onApprove={onSummarize} hidden={loading}>
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={loading}
                        disabledReason="AI data processing must be approved to summarize traces"
                        data-attr="llm-session-summarize-all"
                    >
                        Summarize all traces
                    </LemonButton>
                </AccessControlAction>
            </AIConsentPopoverWrapper>
        )
    }
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.LlmAnalytics}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type="primary"
                size="small"
                onClick={onSummarize}
                loading={loading}
                data-attr="llm-session-summarize-all"
            >
                Summarize all traces
            </LemonButton>
        </AccessControlAction>
    )
}

function SessionTurnView({
    turn,
    phase = 'complete',
    showSentiment,
    showSessionSummarization,
    traceSearchParams,
    rootRef,
}: {
    turn: SessionTurn
    phase?: TurnPhase
    showSentiment: boolean
    showSessionSummarization: boolean
    traceSearchParams: Record<string, unknown>
    rootRef?: Ref<HTMLDivElement>
}): JSX.Element {
    const { traceSummaries, loadingFullTraces, fullTraces, expandedGenerationIds } = useValues(
        aiObservabilitySessionDataLogic
    )
    const { openStepsDrawer, toggleGenerationExpanded, loadFullTrace } = useActions(aiObservabilitySessionDataLogic)

    const trace = turn.trace
    const summary: TraceSummary | undefined = traceSummaries[trace.id]
    const isLoading = loadingFullTraces.has(trace.id)
    const fullTrace = fullTraces[trace.id]
    const baseTraceParams = {
        ...traceSearchParams,
        timestamp: getTraceTimestamp(trace.createdAt),
    }
    const summaryUrl = combineUrl(urls.aiObservabilityTrace(trace.id), { ...baseTraceParams, tab: 'summary' }).url
    const stepCount = (fullTrace?.events ?? []).filter(
        (e) => e.event === '$ai_generation' || e.event === '$ai_span' || e.event === '$ai_embedding'
    ).length
    // Errors already surfaced by a red tool pill are excluded; the rest (e.g.
    // generation failures) render as their own pills in the same style.
    const otherErrors = turn.errors.filter((e) => !turn.tools.includes(e.label))

    const hasTranscript = turn.isLoaded && !!turn.userVisibleTurn
    // Span-only turns have no transcript, so the span tree IS the conversation.
    const isSpanOnly = turn.isLoaded && !turn.userVisibleTurn
    // Only a settled turn shows its summary, tools, errors, steps, and sidebar.
    const isComplete = phase === 'complete'

    return (
        <div className="flex flex-col" ref={rootRef}>
            <div className="flex items-center gap-3 py-3 text-xs text-muted">
                <div className="flex-1 border-t" />
                <TZLabel time={trace.createdAt} formatDate="MMM D, YYYY" formatTime="h:mm A" />
                <div className="flex-1 border-t" />
            </div>
            <div className="pb-4">
                <div className="flex-1 min-w-0 flex flex-col gap-2">
                    {isComplete && showSessionSummarization && summary && (
                        <TurnSummaryLine summary={summary} summaryUrl={summaryUrl} />
                    )}

                    <TurnBody
                        turn={turn}
                        phase={phase}
                        isLoading={isLoading}
                        sentiment={isComplete && showSentiment ? trace.sentiment : undefined}
                        onLoad={() => loadFullTrace(trace.id)}
                    />

                    {isComplete && turn.tools.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap text-xs text-muted">
                            {turn.tools.map((name) => {
                                // Tool spans and error labels both come from `$ai_span_name`,
                                // so an exact match flags the tool call that failed.
                                const toolError = turn.errors.find((e) => e.label === name)
                                const pill = (
                                    <LemonTag
                                        key={name}
                                        size="small"
                                        type={toolError ? 'danger' : undefined}
                                        className="font-mono cursor-pointer hover:bg-fill-button-tertiary-hover"
                                        onClick={() => openStepsDrawer(trace.id, name)}
                                        icon={toolError ? <IconWarning /> : <IconWrench />}
                                    >
                                        {name}
                                    </LemonTag>
                                )
                                return toolError ? (
                                    <Tooltip key={name} title={toolError.message}>
                                        {pill}
                                    </Tooltip>
                                ) : (
                                    pill
                                )
                            })}
                        </div>
                    )}

                    {isComplete && otherErrors.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap text-xs text-muted">
                            {otherErrors.map((e, i) => (
                                <Tooltip key={i} title={e.message}>
                                    <LemonTag
                                        type="danger"
                                        size="small"
                                        className="font-mono cursor-pointer hover:bg-fill-button-tertiary-hover"
                                        onClick={() => openStepsDrawer(trace.id, e.label)}
                                        icon={<IconWarning />}
                                    >
                                        {e.label}
                                    </LemonTag>
                                </Tooltip>
                            ))}
                        </div>
                    )}

                    {isComplete && hasTranscript && (
                        <div>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => openStepsDrawer(trace.id)}
                                data-attr="llm-session-view-steps"
                            >
                                View trace{stepCount > 0 ? ` (${stepCount} ${stepCount === 1 ? 'step' : 'steps'})` : ''}
                            </LemonButton>
                        </div>
                    )}

                    {isComplete && isSpanOnly && (
                        <StepsPanel
                            fullTrace={fullTrace}
                            expandedEventIds={expandedGenerationIds}
                            onToggleEventExpand={toggleGenerationExpanded}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}

function TurnSummaryLine({ summary, summaryUrl }: { summary: TraceSummary; summaryUrl: string }): JSX.Element {
    if (summary.loading) {
        return (
            <div className="flex items-center gap-2 text-muted text-sm">
                <Spinner className="text-lg" />
                <span>Generating summary...</span>
            </div>
        )
    }
    if (summary.error) {
        return (
            <Tooltip title={summary.error}>
                <span className="text-danger text-sm">Failed to generate summary</span>
            </Tooltip>
        )
    }
    return (
        <Link to={summaryUrl} className="text-sm font-medium">
            {summary.title}
        </Link>
    )
}

function TurnBody({
    turn,
    phase = 'complete',
    isLoading,
    sentiment,
    onLoad,
}: {
    turn: SessionTurn
    phase?: TurnPhase
    isLoading: boolean
    sentiment?: LLMTrace['sentiment']
    onLoad: () => void
}): JSX.Element | null {
    if (isLoading) {
        return (
            <div className="flex items-center gap-2 text-muted text-sm py-2">
                <Spinner className="text-lg" />
                <span>Loading conversation…</span>
            </div>
        )
    }
    if (!turn.isLoaded) {
        return (
            <div className="py-2">
                <LemonButton size="small" type="secondary" onClick={onLoad}>
                    Show conversation
                </LemonButton>
            </div>
        )
    }
    if (!turn.userVisibleTurn) {
        // No chat to render — the parent renders `StepsPanel` inline below as the substitute.
        return null
    }
    // Before the request lands, the user is "composing" — a user-side typing indicator.
    if (phase === 'userThinking') {
        return <TypingIndicator type="human" />
    }
    // Request shown, response still in flight — request plus a typing indicator.
    if (phase === 'aiThinking') {
        return (
            <div className="flex flex-col gap-1.5">
                <TranscriptBubbleStream inputs={turn.newInputs} outputs={[]} />
                <TypingIndicator />
            </div>
        )
    }
    // `turn.newInputs` / `outputs` come pre-deduped from `extractSessionTurns`.
    return (
        <div className="flex flex-col gap-1.5">
            <TranscriptBubbleStream inputs={turn.newInputs} outputs={[]} />
            {turn.newInputs.length > 0 && <SessionTraceSentimentBar sentiment={sentiment} />}
            <TranscriptBubbleStream inputs={[]} outputs={turn.outputs} />
        </div>
    )
}

function StepsPanel({
    fullTrace,
    expandedEventIds,
    onToggleEventExpand,
}: {
    fullTrace: LLMTrace | undefined
    expandedEventIds: Set<string>
    onToggleEventExpand: (eventId: string) => void
}): JSX.Element {
    return (
        <div className="border rounded bg-bg-light p-3">
            <AIObservabilityTraceEvents
                trace={fullTrace}
                isLoading={false}
                expandedEventIds={expandedEventIds}
                onToggleEventExpand={onToggleEventExpand}
            />
        </div>
    )
}
