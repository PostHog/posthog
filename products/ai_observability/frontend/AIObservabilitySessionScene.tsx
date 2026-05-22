import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { Suspense, lazy } from 'react'

import { LemonButton, LemonTag, Spinner, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
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

import { AIObservabilityRenameBanner } from './AIObservabilityRenameBanner'
import { TraceSummary, aiObservabilitySessionDataLogic } from './aiObservabilitySessionDataLogic'
import { aiObservabilitySessionLogic } from './aiObservabilitySessionLogic'
import { AIObservabilityTraceEvents } from './components/AIObservabilityTraceEvents'
import { SentimentBar } from './components/SentimentTag'
import { ConversationMessagesDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { SessionTurn } from './extractSessionTurns'
import { llmSentimentLazyLoaderLogic } from './llmSentimentLazyLoaderLogic'
import { SENTIMENT_DATE_WINDOW_DAYS } from './sentimentUtils'
import { formatLLMCost, getTraceTimestamp, sanitizeTraceUrlSearchParams } from './utils'

const LLMASessionFeedbackDisplay = lazy(() =>
    import('./LLMASessionFeedbackDisplay').then((m) => ({ default: m.LLMASessionFeedbackDisplay }))
)

export const scene: SceneExport = {
    component: AIObservabilitySessionScene,
    logic: aiObservabilitySessionLogic,
}

export function AIObservabilitySessionScene({ tabId }: { tabId?: string }): JSX.Element {
    const sessionLogic = aiObservabilitySessionLogic({ tabId })
    const { sessionId, query } = useValues(sessionLogic)
    const sessionDataLogic = aiObservabilitySessionDataLogic({ sessionId, query, tabId })

    useAttachedLogic(sessionDataLogic, sessionLogic)

    return (
        <BindLogic logic={aiObservabilitySessionLogic} props={{ tabId }}>
            <BindLogic logic={aiObservabilitySessionDataLogic} props={{ sessionId, query, tabId }}>
                <SessionSceneWrapper />
            </BindLogic>
        </BindLogic>
    )
}

function SessionTraceSentimentBar({ traceId, createdAt }: { traceId: string; createdAt?: string }): JSX.Element | null {
    const { sentimentByTraceId, isTraceLoading } = useValues(llmSentimentLazyLoaderLogic)
    const { ensureSentimentLoaded } = useActions(llmSentimentLazyLoaderLogic)

    const cached = sentimentByTraceId[traceId]
    const loading = isTraceLoading(traceId)

    if (cached === undefined && !loading) {
        ensureSentimentLoaded(
            traceId,
            createdAt
                ? { dateFrom: createdAt, dateTo: dayjs(createdAt).add(SENTIMENT_DATE_WINDOW_DAYS, 'day').toISOString() }
                : undefined
        )
    }

    if (cached === null) {
        return null
    }

    return (
        <SentimentBar
            label={cached?.label ?? 'neutral'}
            score={cached?.score ?? 0}
            loading={loading || cached === undefined}
            messages={cached?.messages}
        />
    )
}

function SessionSceneWrapper(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const showFeedback = !!featureFlags[FEATURE_FLAGS.POSTHOG_AI_CONVERSATION_FEEDBACK_LLMA_SESSIONS]
    const showSentiment = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SENTIMENT]

    const { traces, responseLoading, responseError, sessionTurns, hasMoreData, nextDataLoading, summariesLoading } =
        useValues(aiObservabilitySessionDataLogic)
    const { sessionId } = useValues(aiObservabilitySessionLogic)
    const { summarizeAllTraces, loadNextData } = useActions(aiObservabilitySessionDataLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    // Compute the URL search-param passthrough once for the page, not per turn —
    // every `SessionTurnView` consumes the same `traceSearchParams`.
    const { searchParams } = useValues(router)
    const traceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })

    const showSessionSummarization =
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SESSION_SUMMARIZATION] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

    // Calculate session aggregates
    const sessionStats = traces.reduce(
        (acc, trace) => ({
            totalCost: acc.totalCost + (trace.totalCost || 0),
            totalLatency: acc.totalLatency + (trace.totalLatency || 0),
            traceCount: acc.traceCount + 1,
        }),
        { totalCost: 0, totalLatency: 0, traceCount: 0 }
    )

    if (responseLoading) {
        return <SpinnerOverlay />
    }
    if (responseError) {
        return <InsightErrorState />
    }
    if (!traces || traces.length === 0) {
        return <InsightEmptyState heading="No traces found" detail="This session has no traces." />
    }

    return (
        <div className="relative flex flex-col gap-4">
            <SceneBreadcrumbBackButton />
            <AIObservabilityRenameBanner />
            <header className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex gap-1.5 flex-wrap">
                    <LemonTag size="medium" className="bg-surface-primary">
                        <span className="font-mono">{sessionId}</span>
                    </LemonTag>
                    <LemonTag size="medium" className="bg-surface-primary">
                        {sessionStats.traceCount}
                        {hasMoreData ? '+' : ''} {sessionStats.traceCount === 1 ? 'turn' : 'turns'}
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
                {showSessionSummarization && (
                    <SummarizeAllButton
                        loading={summariesLoading}
                        dataProcessingAccepted={dataProcessingAccepted}
                        onSummarize={summarizeAllTraces}
                    />
                )}
            </header>

            <div className="flex flex-col">
                {sessionTurns.map((turn, index) => (
                    <SessionTurnView
                        key={turn.trace.id}
                        turn={turn}
                        turnNumber={index + 1}
                        showSentiment={showSentiment}
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
                            Load more turns
                        </LemonButton>
                    </div>
                )}
            </div>
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
                        Summarize all turns
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
                Summarize all turns
            </LemonButton>
        </AccessControlAction>
    )
}

function SessionTurnView({
    turn,
    turnNumber,
    showSentiment,
    showSessionSummarization,
    traceSearchParams,
}: {
    turn: SessionTurn
    turnNumber: number
    showSentiment: boolean
    showSessionSummarization: boolean
    traceSearchParams: Record<string, unknown>
}): JSX.Element {
    const { traceSummaries, loadingFullTraces, fullTraces, reasoningExpandedTraceIds, expandedGenerationIds } =
        useValues(aiObservabilitySessionDataLogic)
    const { toggleReasoning, toggleGenerationExpanded, loadFullTrace } = useActions(aiObservabilitySessionDataLogic)

    const trace = turn.trace
    const summary: TraceSummary | undefined = traceSummaries[trace.id]
    const isLoading = loadingFullTraces.has(trace.id)
    const reasoningShown = reasoningExpandedTraceIds.has(trace.id)
    const fullTrace = fullTraces[trace.id]
    const baseTraceParams = {
        ...traceSearchParams,
        timestamp: getTraceTimestamp(trace.createdAt),
    }
    const traceUrl = combineUrl(urls.aiObservabilityTrace(trace.id), baseTraceParams).url
    const summaryUrl = combineUrl(urls.aiObservabilityTrace(trace.id), { ...baseTraceParams, tab: 'summary' }).url

    return (
        <div className="flex flex-col gap-2 py-4 border-t first:border-t-0 first:pt-0">
            <div className="flex items-center gap-2 flex-wrap text-xs text-muted">
                <span className="font-semibold text-default">Turn {turnNumber}</span>
                {(trace.errorCount ?? 0) > 0 && (
                    <LemonTag type="danger" size="small">
                        {trace.errorCount === 1 ? '1 error' : `${trace.errorCount} errors`}
                    </LemonTag>
                )}
                {typeof trace.totalLatency === 'number' && <span>{trace.totalLatency.toFixed(2)}s</span>}
                {typeof trace.totalCost === 'number' && <span>· {formatLLMCost(trace.totalCost)}</span>}
                <span>
                    · <TZLabel time={trace.createdAt} />
                </span>
                {showSentiment && (
                    <span className="ml-1">
                        <SessionTraceSentimentBar traceId={trace.id} createdAt={trace.createdAt} />
                    </span>
                )}
                <div className="flex-1" />
                <Link to={traceUrl} className="text-xs">
                    Open trace →
                </Link>
            </div>

            {showSessionSummarization && summary && <TurnSummaryLine summary={summary} summaryUrl={summaryUrl} />}

            <TurnBody turn={turn} isLoading={isLoading} onLoad={() => loadFullTrace(trace.id)} />

            {turn.isLoaded && turn.userVisibleTurn && (
                <ReasoningToggle
                    traceId={trace.id}
                    fullTrace={fullTrace}
                    reasoningShown={reasoningShown}
                    onToggle={() => toggleReasoning(trace.id)}
                    expandedEventIds={expandedGenerationIds}
                    onToggleEventExpand={toggleGenerationExpanded}
                />
            )}
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
    isLoading,
    onLoad,
}: {
    turn: SessionTurn
    isLoading: boolean
    onLoad: () => void
}): JSX.Element {
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
        return <div className="text-muted text-sm py-2">No conversational turn to render in this trace.</div>
    }
    // `turn.newInputs` / `outputs` come pre-deduped from `extractSessionTurns`.
    // Rendering goes through the same `ConversationMessagesDisplay` the Trace page
    // uses, so parser coverage is identical: shapes recognized by `normalizeMessage`
    // render natively, anything else falls back to JSON. See `extractSessionTurns.ts`
    // and `messageSignature.ts` for the dedup + user-visible-turn conventions.
    return (
        <ConversationMessagesDisplay
            inputNormalized={turn.newInputs}
            outputNormalized={turn.outputs}
            inputSourceIndices={turn.newInputSourceIndices}
            errorData={turn.userVisibleTurn.properties.$ai_error}
            httpStatus={turn.userVisibleTurn.properties.$ai_http_status}
            raisedError={turn.userVisibleTurn.properties.$ai_is_error}
            bordered
            // Explicit so the Session view doesn't silently inherit a future
            // change to the Trace page's default — the two surfaces can diverge.
            displayOption="collapse_except_output_and_last_input"
            traceId={turn.userVisibleTurn.properties.$ai_trace_id}
            generationEventId={turn.userVisibleTurn.id}
        />
    )
}

function ReasoningToggle({
    traceId,
    fullTrace,
    reasoningShown,
    onToggle,
    expandedEventIds,
    onToggleEventExpand,
}: {
    traceId: string
    fullTrace: LLMTrace | undefined
    reasoningShown: boolean
    onToggle: () => void
    expandedEventIds: Set<string>
    onToggleEventExpand: (eventId: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <button
                type="button"
                onClick={onToggle}
                className="self-start text-xs text-muted hover:text-default underline"
            >
                {reasoningShown ? 'Hide reasoning' : 'Show reasoning'}
            </button>
            {reasoningShown && (
                <div className="border rounded bg-bg-light p-3">
                    <AIObservabilityTraceEvents
                        trace={fullTrace}
                        isLoading={false}
                        expandedEventIds={expandedEventIds}
                        onToggleEventExpand={onToggleEventExpand}
                        traceId={traceId}
                    />
                </div>
            )}
        </div>
    )
}
