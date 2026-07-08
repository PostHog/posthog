import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import {
    AnyResponseType,
    DataTableNode,
    LLMTrace,
    LLMTraceEvent,
    NodeKind,
    SessionQueryResponse,
    TraceQuery,
} from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { aiObservabilitySessionDataLogicType } from './aiObservabilitySessionDataLogicType'
import { aiObservabilitySessionLogic } from './aiObservabilitySessionLogic'
import { restoreTree } from './aiObservabilityTraceDataLogic'
import { SessionTurn, extractSessionTurns } from './extractSessionTurns'
import { llmAnalyticsSummarizationBatchCheckCreate } from './generated/api'
import { eventLabel } from './utils'

export interface TraceSummary {
    title: string
    traceId: string
    loading: boolean
    error: string | null
}

type SessionDateRange = { dateFrom: string | null; dateTo: string | null } | null

export interface SessionDataLogicProps {
    sessionId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

function getDataNodeLogicProps({ sessionId, query, cachedResults }: SessionDataLogicProps): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Session.${sessionId}`,
        dataNodeCollectionId: sessionId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: sessionId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

function getTraceQueryDateRange(dateRange: SessionDateRange): TraceQuery['dateRange'] {
    if (!dateRange?.dateFrom && !dateRange?.dateTo) {
        return undefined
    }

    return {
        date_from: dateRange.dateFrom || undefined,
        date_to: dateRange.dateTo || undefined,
    }
}

function getDateRangeCacheKey(dateRange: SessionDateRange): string {
    return `${dateRange?.dateFrom ?? ''}\0${dateRange?.dateTo ?? ''}`
}

function getFirstTraceStepEventId(trace: LLMTrace): string | null {
    const firstEvent = trace.events
        ?.filter((e) => e.event === '$ai_generation' || e.event === '$ai_span' || e.event === '$ai_embedding')
        .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())[0]
    return firstEvent?.id ?? null
}

// Maps a clicked tool/error pill to the trace event it represents so the drawer
// can pre-expand that step. Tool spans and error labels both derive from the
// event's `$ai_span_name`/`$ai_model` (via `eventLabel`), so an exact label match
// finds the step; prefer the errored event when several share a label.
function resolveFocusEventId(trace: LLMTrace, focusKey: string): string | null {
    const events = trace.events ?? []
    const isError = (e: LLMTraceEvent): boolean =>
        e.properties?.$ai_is_error === true || e.properties?.$ai_is_error === 'true' || !!e.properties?.$ai_error
    const match =
        events.find((e) => eventLabel(e) === focusKey && isError(e)) ?? events.find((e) => eventLabel(e) === focusKey)
    return match?.id ?? null
}

export const aiObservabilitySessionDataLogic = kea<aiObservabilitySessionDataLogicType>([
    path(['scenes', 'ai-observability', 'aiObservabilitySessionDataLogic']),
    props({} as SessionDataLogicProps),
    key((props) => `${props.sessionId}`),
    connect((props: SessionDataLogicProps) => ({
        values: [
            aiObservabilitySessionLogic,
            ['sessionId', 'dateRange'],
            dataNodeLogic(getDataNodeLogicProps(props)),
            ['response', 'responseLoading', 'responseError', 'canLoadNextData', 'hasMoreData', 'nextDataLoading'],
            maxGlobalLogic,
            ['dataProcessingAccepted'],
            teamLogic,
            ['currentTeamId'],
        ],
        actions: [
            aiObservabilitySessionLogic,
            ['setDateRange'],
            dataNodeLogic(getDataNodeLogicProps(props)),
            ['loadNextData'],
        ],
    })),

    actions({
        // Which trace's steps are open in the side drawer (one at a time, or null).
        // `focusEventKey` (a tool name / error label) pre-expands the matching step.
        openStepsDrawer: (traceId: string, focusEventKey: string | null = null) => ({ traceId, focusEventKey }),
        closeStepsDrawer: true,
        toggleGenerationExpanded: (generationId: string) => ({ generationId }),
        // Expand only this step, collapsing the rest (timeline / pill focus).
        focusGenerationExpanded: (generationId: string) => ({ generationId }),
        clearTraceDetails: true,
        loadFullTrace: (traceId: string) => ({ traceId }),
        loadFullTraceSuccess: (traceId: string, trace: LLMTrace, dateRangeCacheKey: string) => ({
            traceId,
            trace,
            dateRangeCacheKey,
        }),
        loadFullTraceFailure: (traceId: string) => ({ traceId }),
        loadCachedSummaries: (traceIds: string[]) => ({ traceIds }),
        loadCachedSummariesSuccess: (summaries: Array<{ trace_id: string; title: string }>) => ({ summaries }),
        summarizeAllTraces: true,
        summarizeTrace: (traceId: string, forceRefresh: boolean = false) => ({ traceId, forceRefresh }),
        summarizeTraceSuccess: (traceId: string, title: string) => ({ traceId, title }),
        summarizeTraceFailure: (traceId: string, error: string) => ({ traceId, error }),
        clearTraceSummaries: true,
    }),

    reducers({
        drawerTraceId: [
            null as string | null,
            {
                openStepsDrawer: (_, { traceId }) => traceId,
                closeStepsDrawer: () => null,
                clearTraceDetails: () => null,
            },
        ],
        // A pending tool/error label to focus once the drawer's trace finishes loading.
        drawerFocusKey: [
            null as string | null,
            {
                openStepsDrawer: (_, { focusEventKey }) => focusEventKey,
                closeStepsDrawer: () => null,
                focusGenerationExpanded: () => null,
                clearTraceDetails: () => null,
            },
        ],
        expandedGenerationIds: [
            new Set<string>() as Set<string>,
            {
                toggleGenerationExpanded: (state, { generationId }) => {
                    const newSet = new Set(state)
                    if (newSet.has(generationId)) {
                        newSet.delete(generationId)
                    } else {
                        newSet.add(generationId)
                    }
                    return newSet
                },
                focusGenerationExpanded: (_, { generationId }) => new Set([generationId]),
                clearTraceDetails: () => new Set<string>(),
            },
        ],
        fullTraces: [
            {} as Record<string, LLMTrace>,
            {
                loadFullTraceSuccess: (state, { traceId, trace }) => ({
                    ...state,
                    [traceId]: trace,
                }),
                clearTraceDetails: () => ({}),
            },
        ],
        fullTraceDateRangeCacheKeys: [
            {} as Record<string, string>,
            {
                loadFullTraceSuccess: (state, { traceId, dateRangeCacheKey }) => ({
                    ...state,
                    [traceId]: dateRangeCacheKey,
                }),
                clearTraceDetails: () => ({}),
            },
        ],
        loadingFullTraces: [
            new Set<string>() as Set<string>,
            {
                loadFullTrace: (state, { traceId }) => new Set(state).add(traceId),
                loadFullTraceSuccess: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.delete(traceId)
                    return newSet
                },
                loadFullTraceFailure: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.delete(traceId)
                    return newSet
                },
                clearTraceDetails: () => new Set<string>(),
            },
        ],
        traceSummaries: [
            {} as Record<string, TraceSummary>,
            {
                loadCachedSummariesSuccess: (state, { summaries }) => {
                    const newState = { ...state }
                    for (const summary of summaries) {
                        newState[summary.trace_id] = {
                            traceId: summary.trace_id,
                            title: summary.title,
                            loading: false,
                            error: null,
                        }
                    }
                    return newState
                },
                summarizeTrace: (state, { traceId }) => ({
                    ...state,
                    [traceId]: { traceId, title: '', loading: true, error: null },
                }),
                summarizeTraceSuccess: (state, { traceId, title }) => ({
                    ...state,
                    [traceId]: { traceId, title, loading: false, error: null },
                }),
                summarizeTraceFailure: (state, { traceId, error }) => ({
                    ...state,
                    [traceId]: { ...state[traceId], loading: false, error },
                }),
                clearTraceSummaries: () => ({}),
            },
        ],
    }),

    selectors({
        traces: [
            (s) => [s.response],
            (response: AnyResponseType | null): LLMTrace[] => {
                const tracesResponse = response as SessionQueryResponse | null
                // Reverse to chronological order (oldest first) for session view
                return [...(tracesResponse?.results || [])].reverse()
            },
        ],
        sessionTurns: [
            (s) => [s.traces, s.fullTraces],
            (traces: LLMTrace[], fullTraces: Record<string, LLMTrace>): SessionTurn[] =>
                extractSessionTurns(traces, fullTraces),
        ],
        summariesLoading: [
            (s) => [s.traceSummaries],
            (traceSummaries: Record<string, TraceSummary>): boolean =>
                Object.values(traceSummaries).some((s) => s.loading),
        ],
        initialLoading: [(s) => [s.responseLoading], (responseLoading: boolean): boolean => responseLoading],
    }),

    listeners(({ actions, values }) => {
        // Closure-scoped in-flight lock for `loadFullTrace`. Mirrors the pattern used
        // by sibling lazy loaders in this product (llmPersonsLazyLoaderLogic,
        // traceReviewsLazyLoaderLogic, etc.). We can't
        // rely on `values.loadingFullTraces` for this guard because kea reducers run
        // synchronously *before* listeners — so the reducer has already added this
        // traceId by the time the listener checks. The closure-scoped Set lets the
        // listener distinguish "this dispatch's reducer just added the id" from
        // "a prior dispatch is still mid-flight".
        const inFlightTraceFetches = new Set<string>()

        return {
            setDateRange: () => {
                actions.clearTraceDetails()
            },
            loadCachedSummaries: async ({ traceIds }) => {
                if (traceIds.length === 0) {
                    return
                }

                if (!values.dataProcessingAccepted) {
                    return
                }

                const teamId = values.currentTeamId
                if (!teamId) {
                    return
                }

                try {
                    const data = await llmAnalyticsSummarizationBatchCheckCreate(String(teamId), {
                        trace_ids: traceIds,
                        mode: 'minimal',
                    })

                    if (data.summaries && data.summaries.length > 0) {
                        actions.loadCachedSummariesSuccess(data.summaries)
                    }
                } catch {
                    // Silently fail - this is just a cache optimization
                }
            },
            loadFullTrace: async ({ traceId }) => {
                const dateRangeCacheKey = getDateRangeCacheKey(values.dateRange)
                if (
                    (values.fullTraces[traceId] && values.fullTraceDateRangeCacheKeys[traceId] === dateRangeCacheKey) ||
                    inFlightTraceFetches.has(`${traceId}:${dateRangeCacheKey}`)
                ) {
                    return
                }
                inFlightTraceFetches.add(`${traceId}:${dateRangeCacheKey}`)
                const dateRange = getTraceQueryDateRange(values.dateRange)
                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
                    includeSentiment: true,
                    dateRange,
                }
                try {
                    const response = await api.query(traceQuery)
                    if (dateRangeCacheKey !== getDateRangeCacheKey(values.dateRange)) {
                        return
                    }
                    if (response.results && response.results[0]) {
                        actions.loadFullTraceSuccess(traceId, response.results[0], dateRangeCacheKey)
                    } else {
                        actions.loadFullTraceFailure(traceId)
                    }
                } catch (error) {
                    console.error('Error loading full trace:', error)
                    actions.loadFullTraceFailure(traceId)
                } finally {
                    inFlightTraceFetches.delete(`${traceId}:${dateRangeCacheKey}`)
                }
            },
            openStepsDrawer: ({ traceId, focusEventKey }) => {
                const trace = values.fullTraces[traceId]
                const dateRangeCacheKey = getDateRangeCacheKey(values.dateRange)
                const isTraceFresh = !!trace && values.fullTraceDateRangeCacheKeys[traceId] === dateRangeCacheKey
                if (!isTraceFresh && !values.loadingFullTraces.has(traceId)) {
                    actions.loadFullTrace(traceId)
                }
                // Already loaded: focus the clicked step now. Otherwise the
                // loadFullTraceSuccess listener picks it up once events arrive.
                if (isTraceFresh && trace) {
                    const id = focusEventKey
                        ? resolveFocusEventId(trace, focusEventKey)
                        : getFirstTraceStepEventId(trace)
                    if (id) {
                        actions.focusGenerationExpanded(id)
                    }
                }
            },
            loadFullTraceSuccess: ({ traceId, trace }) => {
                if (traceId === values.drawerTraceId) {
                    const id = values.drawerFocusKey
                        ? resolveFocusEventId(trace, values.drawerFocusKey)
                        : getFirstTraceStepEventId(trace)
                    if (id) {
                        actions.focusGenerationExpanded(id)
                    }
                }
            },
            summarizeAllTraces: async () => {
                if (!values.dataProcessingAccepted) {
                    return
                }

                const hasSummaries = Object.keys(values.traceSummaries).length > 0
                const traces = values.traces
                for (const trace of traces) {
                    actions.summarizeTrace(trace.id, hasSummaries)
                }
            },
            summarizeTrace: async ({ traceId, forceRefresh }) => {
                const teamId = values.currentTeamId
                if (!teamId) {
                    actions.summarizeTraceFailure(traceId, 'Team ID not available')
                    return
                }

                try {
                    // If a trace is missing from the session response, fetch it directly as a fallback.
                    let fullTrace: LLMTrace | undefined = values.fullTraces[traceId]
                    if (!fullTrace) {
                        const dateRange = getTraceQueryDateRange(values.dateRange)
                        const traceQuery: TraceQuery = {
                            kind: NodeKind.TraceQuery,
                            traceId,
                            dateRange,
                        }
                        const traceResponse = await api.query(traceQuery)
                        if (traceResponse.results && traceResponse.results[0]) {
                            fullTrace = traceResponse.results[0]
                        } else {
                            throw new Error('Failed to load full trace')
                        }
                    }

                    // Build the hierarchy tree from full trace events
                    const hierarchy = restoreTree(fullTrace.events || [], traceId)

                    // nosemgrep: prefer-codegen-api
                    const data = await api.create(`api/environments/${teamId}/llm_analytics/summarization/`, {
                        summarize_type: 'trace',
                        mode: 'minimal',
                        force_refresh: forceRefresh,
                        data: {
                            trace: fullTrace,
                            hierarchy,
                        },
                    })

                    actions.summarizeTraceSuccess(traceId, data.summary?.title || 'Untitled trace')
                } catch (error) {
                    actions.summarizeTraceFailure(traceId, error instanceof Error ? error.message : 'Unknown error')
                }
            },
        }
    }),

    subscriptions(({ actions, values }) => ({
        traces: (traces: LLMTrace[]) => {
            if (traces.length === 0) {
                return
            }
            const dateRangeCacheKey = getDateRangeCacheKey(values.dateRange)
            for (const trace of traces) {
                if (trace.events?.length > 0 && values.fullTraceDateRangeCacheKeys[trace.id] !== dateRangeCacheKey) {
                    actions.loadFullTraceSuccess(trace.id, trace, dateRangeCacheKey)
                }
            }
            // Cache lookup for existing trace summaries
            if (Object.keys(values.traceSummaries).length === 0) {
                actions.loadCachedSummaries(traces.map((t) => t.id))
            }
        },
    })),
])
