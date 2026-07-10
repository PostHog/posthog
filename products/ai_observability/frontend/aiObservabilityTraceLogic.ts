import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api, { ApiConfig } from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProductIntent } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import {
    AnyResponseType,
    DataTableNode,
    NodeKind,
    ProductIntentContext,
    ProductKey,
    TraceNeighborsQuery,
    TraceNeighborsQueryResponse,
    TraceQuery,
} from '~/queries/schema/schema-general'
import { ActivityScope, AnyPropertyFilter, Breadcrumb, InsightLogicProps } from '~/types'

import { engineeringAnalyticsResolveBranch } from 'products/engineering_analytics/frontend/generated/api'
import type { BranchPRMatchApi } from 'products/engineering_analytics/frontend/generated/api.schemas'

import { aiObservabilitySharedLogic } from './aiObservabilitySharedLogic'
import type { aiObservabilityTraceLogicType } from './aiObservabilityTraceLogicType'
import { buildAiObservabilityStorageConfig } from './preferenceStorage'

export enum DisplayOption {
    ExpandAll = 'expand_all',
    ExpandUserOnly = 'expand_user_only',
    CollapseExceptOutputAndLastInput = 'collapse_except_output_and_last_input',
    TextView = 'text_view',
}

export enum TraceViewMode {
    Conversation = 'conversation',
    Raw = 'raw',
    Summary = 'summary',
    Evals = 'evals',
    Tags = 'tags',
    Clusters = 'clusters',
    Feedback = 'feedback',
}

export interface AIObservabilityTraceDataNodeLogicParams {
    traceId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

const EXCEPTION_LOOKUP_WINDOW_MINUTES = 20

export function getDataNodeLogicProps({
    traceId,
    query,
    cachedResults,
}: AIObservabilityTraceDataNodeLogicParams): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Trace.${traceId}`,
        dataNodeCollectionId: traceId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: traceId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

export type AIObservabilityTraceLogicProps = Record<string, never>

/** Git ref stamped on a trace's events by a coding-agent session (branch-only MVP; either field may be null). */
export interface TraceGitMetadata {
    branch: string | null
    repo: string | null
}

/** A branch→PR resolution tagged with the request it resolved for, so a result left over from a
 * previously viewed trace can be ignored until the reload for the new trace finishes. */
export interface BranchPRResolution {
    key: string | null
    matches: BranchPRMatchApi[]
}

/** Identity of one resolution request. Branch alone is not enough: two traces can carry the same
 * branch name in different repos, and a branch-only guard would link one repo's chip to the other's PR. */
export function branchPRResolutionKey(gitMetadata: TraceGitMetadata | null): string | null {
    return gitMetadata?.branch ? `${gitMetadata.repo ?? ''}::${gitMetadata.branch}` : null
}

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const aiObservabilityTraceLogic = kea<aiObservabilityTraceLogicType>([
    path(['scenes', 'ai-observability', 'aiObservabilityTraceLogic']),
    props({} as AIObservabilityTraceLogicProps),

    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            aiObservabilitySharedLogic,
            ['dateFilter', 'propertyFilters', 'shouldFilterTestAccounts', 'shouldFilterSupportTraces'],
        ],
    })),

    actions({
        setTraceId: (traceId: string) => ({ traceId }),
        setEventId: (eventId: string | null) => ({ eventId }),
        setHighlightMessageIndex: (highlightMessageIndex: number | null) => ({ highlightMessageIndex }),
        setLineNumber: (lineNumber: number | null) => ({ lineNumber }),
        setInitialTab: (tab: string | null) => ({ tab }),
        setDateRange: (dateFrom: string | null, dateTo?: string | null) => ({ dateFrom, dateTo }),
        setIsRenderingMarkdown: (isRenderingMarkdown: boolean) => ({ isRenderingMarkdown }),
        toggleMarkdownRendering: true,
        setIsRenderingXml: (isRenderingXml: boolean) => ({ isRenderingXml }),
        toggleXmlRendering: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        initializeMessageStates: (inputCount: number, outputCount: number) => ({ inputCount, outputCount }),
        toggleMessage: (type: 'input' | 'output', index: number) => ({ type, index }),
        showAllMessages: (type: 'input' | 'output') => ({ type }),
        hideAllMessages: (type: 'input' | 'output') => ({ type }),
        applySearchResults: (inputMatches: boolean[], outputMatches: boolean[]) => ({ inputMatches, outputMatches }),
        setDisplayOption: (displayOption: DisplayOption) => ({ displayOption }),
        handleTextViewFallback: true,
        copyLinePermalink: (lineNumber: number) => ({ lineNumber }),
        toggleEventTypeExpanded: (eventType: string) => ({ eventType }),
        setTraceReviewPanelExpanded: (isExpanded: boolean) => ({ isExpanded }),
        loadCommentCount: true,
        setViewMode: (viewMode: TraceViewMode) => ({ viewMode }),
        loadNeighbors: (traceId: string, timestamp: string) => ({ traceId, timestamp }),
    }),

    reducers(() => ({
        traceId: ['' as string, { setTraceId: (_, { traceId }) => traceId }],
        // The branch+repo the loader is currently resolving for. Updates synchronously when the load is
        // dispatched (before the request resolves), so the branchPRMatches selector can drop a
        // resolution still tagged with the previously viewed trace's branch/repo.
        resolvingKey: [
            null as string | null,
            { loadBranchPRMatches: (_, gitMetadata: TraceGitMetadata | null) => branchPRResolutionKey(gitMetadata) },
        ],
        eventId: [null as string | null, { setEventId: (_, { eventId }) => eventId }],
        highlightMessageIndex: [
            null as number | null,
            { setHighlightMessageIndex: (_, { highlightMessageIndex }) => highlightMessageIndex },
        ],
        lineNumber: [null as number | null, { setLineNumber: (_, { lineNumber }) => lineNumber }],
        initialTab: [null as string | null, { setInitialTab: (_, { tab }) => tab }],
        viewMode: [
            TraceViewMode.Conversation as TraceViewMode,
            {
                setViewMode: (_, { viewMode }) => viewMode,
                setInitialTab: (_, { tab }) => {
                    if (tab === 'summary') {
                        return TraceViewMode.Summary
                    }
                    if (tab === 'raw') {
                        return TraceViewMode.Raw
                    }
                    if (tab === 'evals') {
                        return TraceViewMode.Evals
                    }
                    if (tab === 'clusters') {
                        return TraceViewMode.Clusters
                    }
                    if (tab === 'tags') {
                        return TraceViewMode.Tags
                    }
                    if (tab === 'feedback') {
                        return TraceViewMode.Feedback
                    }
                    return TraceViewMode.Conversation
                },
            },
        ],
        dateRange: [
            null as { dateFrom: string | null; dateTo: string | null } | null,
            {
                setDateRange: (_, { dateFrom, dateTo }) => ({
                    dateFrom: dateFrom ?? null,
                    dateTo: dateTo ?? null,
                }),
            },
        ],
        searchQuery: ['' as string, { setSearchQuery: (_, { searchQuery }) => String(searchQuery || '') }],
        isRenderingMarkdown: [
            true as boolean,
            buildAiObservabilityStorageConfig('trace.isRenderingMarkdown'),
            {
                setIsRenderingMarkdown: (_, { isRenderingMarkdown }) => isRenderingMarkdown,
                toggleMarkdownRendering: (state) => !state,
            },
        ],
        isRenderingXml: [
            false as boolean,
            buildAiObservabilityStorageConfig('trace.isRenderingXml'),
            {
                setIsRenderingXml: (_, { isRenderingXml }) => isRenderingXml,
                toggleXmlRendering: (state) => !state,
            },
        ],
        // Single source of truth for message visibility
        messageShowStates: [
            { input: [] as boolean[], output: [] as boolean[] },
            {
                initializeMessageStates: (_, { inputCount, outputCount }) => {
                    // Will be initialized based on display option in listener
                    const inputStates = Array.from({ length: inputCount }, () => false)
                    const outputStates = Array.from({ length: outputCount }, () => true)
                    return { input: inputStates, output: outputStates }
                },
                toggleMessage: (state, { type, index }) => {
                    const newStates = { ...state }
                    newStates[type] = [...state[type]]
                    newStates[type][index] = !newStates[type][index]
                    return newStates
                },
                showAllMessages: (state, { type }) => {
                    const newStates = { ...state }
                    newStates[type] = state[type].map(() => true)
                    return newStates
                },
                hideAllMessages: (state, { type }) => {
                    const newStates = { ...state }
                    newStates[type] = state[type].map(() => false)
                    return newStates
                },
                applySearchResults: (_, { inputMatches, outputMatches }) => {
                    // When search results come in, expand messages with matches
                    return {
                        input: inputMatches,
                        output: outputMatches,
                    }
                },
                setSearchQuery: (state) => {
                    // Keep current state when search query changes (will be updated by applySearchResults)
                    return state
                },
            },
        ],
        displayOption: [
            DisplayOption.CollapseExceptOutputAndLastInput as DisplayOption,
            buildAiObservabilityStorageConfig('trace.displayOption'),
            {
                setDisplayOption: (_, { displayOption }) => displayOption,
                handleTextViewFallback: () => DisplayOption.ExpandAll,
            },
        ],
        eventTypeExpandedMap: [
            {} as Record<string, boolean>,
            buildAiObservabilityStorageConfig('trace.eventTypeExpandedMap'),
            {
                toggleEventTypeExpanded: (state, { eventType }) => ({
                    ...state,
                    [eventType]: !(state[eventType] ?? true),
                }),
            },
        ],
        isTraceReviewPanelExpanded: [
            false as boolean,
            buildAiObservabilityStorageConfig('trace.isTraceReviewPanelExpanded'),
            {
                setTraceReviewPanelExpanded: (_, { isExpanded }) => isExpanded,
            },
        ],
    })),

    loaders(({ values }) => ({
        commentCount: [
            0,
            {
                loadCommentCount: async (_, breakpoint) => {
                    if (!values.traceId) {
                        return 0
                    }

                    await breakpoint(100)
                    const response = await api.comments.getCount({
                        scope: ActivityScope.LLM_TRACE,
                        item_id: values.traceId,
                        exclude_emoji_reactions: true,
                    })

                    breakpoint()

                    return response
                },
            },
        ],
        neighbors: [
            null as TraceNeighborsQueryResponse | null,
            {
                loadNeighbors: async ({ traceId, timestamp }, breakpoint) => {
                    // Check if feature flag is enabled
                    if (!values.featureFlags?.[FEATURE_FLAGS.LLM_ANALYTICS_TRACE_NAVIGATION]) {
                        return null
                    }

                    if (!traceId || !timestamp) {
                        return null
                    }

                    await breakpoint(100)

                    // Only pass dateRange if it's an explicit date (not a relative default like "-1h" or "dStart")
                    // Relative dates start with "-" or "d" and are defaults, not user-selected filters
                    const hasExplicitDateRange =
                        values.dateFilter?.dateFrom &&
                        !values.dateFilter.dateFrom.startsWith('-') &&
                        !values.dateFilter.dateFrom.startsWith('d')

                    const query: TraceNeighborsQuery = {
                        kind: NodeKind.TraceNeighborsQuery,
                        traceId,
                        timestamp,
                        dateRange: hasExplicitDateRange
                            ? {
                                  date_from: values.dateFilter.dateFrom,
                                  date_to: values.dateFilter.dateTo,
                              }
                            : undefined,
                        filterTestAccounts: values.shouldFilterTestAccounts,
                        filterSupportTraces: values.shouldFilterSupportTraces,
                        properties: values.propertyFilters as AnyPropertyFilter[],
                    }

                    const response = await api.query(query)

                    breakpoint()

                    return response as TraceNeighborsQueryResponse
                },
            },
        ],
        branchPRResolution: [
            { key: null, matches: [] } as BranchPRResolution,
            {
                loadBranchPRMatches: async (gitMetadata: TraceGitMetadata | null, breakpoint) => {
                    // Tag the result with the branch+repo it resolved for, so a stale in-flight result from
                    // the previously viewed trace can be discarded (see the branchPRMatches selector).
                    const key = branchPRResolutionKey(gitMetadata)
                    const branch = gitMetadata?.branch ?? null

                    // Gated on engineering analytics: only that product can turn a git branch into a PR link.
                    if (!branch || !values.featureFlags?.[FEATURE_FLAGS.ENGINEERING_ANALYTICS]) {
                        return { key, matches: [] }
                    }

                    await breakpoint(100)

                    // A failed resolution just means no PR link, the chip renders plain and never blocks the header.
                    let matches: BranchPRMatchApi[]
                    try {
                        matches = await engineeringAnalyticsResolveBranch(projectId(), {
                            branch,
                            repo: gitMetadata?.repo ?? undefined,
                        })
                    } catch {
                        matches = []
                    }

                    // Also on the failure path: a stale request failing after a newer load resolved must not
                    // overwrite the newer resolution.
                    breakpoint()

                    return { key, matches }
                },
            },
        ],
    })),

    selectors({
        // Only surface matches once the stored resolution matches the branch+repo currently being
        // resolved. On a trace switch traceGitMetadata (and resolvingKey) update immediately while the
        // loader still holds the previous trace's matches, so this drops them until the reload lands —
        // the chip never links the new trace's text to another branch's (or same-named branch in
        // another repo's) PR.
        branchPRMatches: [
            (s) => [s.branchPRResolution, s.resolvingKey],
            (resolution, resolvingKey): BranchPRMatchApi[] =>
                resolution.key === resolvingKey ? resolution.matches : [],
        ],
        inputMessageShowStates: [(s) => [s.messageShowStates], (messageStates) => messageStates.input],
        outputMessageShowStates: [(s) => [s.messageShowStates], (messageStates) => messageStates.output],
        query: [
            (s) => [s.traceId, s.dateRange],
            (traceId, dateRange): DataTableNode => {
                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
                    includeSentiment: true,
                    dateRange: dateRange?.dateFrom
                        ? // dateFrom is a minimum timestamp of an event for a trace.
                          {
                              date_from: dateRange.dateFrom,
                              date_to: dateRange?.dateTo || dayjs(dateRange.dateFrom).add(10, 'minutes').toISOString(),
                          }
                        : // By default will look for traces from the beginning.
                          {
                              date_from: dayjs.utc(new Date(2025, 0, 10)).toISOString(),
                          },
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: traceQuery,
                }
            },
        ],

        breadcrumbs: [
            (s) => [s.traceId, router.selectors.searchParams],
            (traceId: string, searchParams: Record<string, any>): Breadcrumb[] => {
                return [
                    {
                        key: 'AIObservability',
                        name: 'AI observability',
                        path: combineUrl(urls.aiObservabilityDashboard(), searchParams).url,
                        iconType: 'llm_analytics',
                    },
                    {
                        key: 'AIObservabilityTraces',
                        name: 'Traces',
                        path: combineUrl(urls.aiObservabilityTraces(), searchParams).url,
                        iconType: 'llm_analytics',
                    },
                    {
                        key: ['AIObservabilityTrace', traceId || ''],
                        name: traceId,
                        iconType: 'llm_analytics',
                    },
                ]
            },
        ],
        eventTypeExpanded: [
            (s) => [s.eventTypeExpandedMap],
            (eventTypeExpandedMap) =>
                (eventType: string): boolean => {
                    return eventTypeExpandedMap[eventType] ?? true
                },
        ],
        newerTraceId: [(s) => [s.neighbors], (neighbors) => neighbors?.newerTraceId ?? null],
        newerTimestamp: [(s) => [s.neighbors], (neighbors) => neighbors?.newerTimestamp ?? null],
        olderTraceId: [(s) => [s.neighbors], (neighbors) => neighbors?.olderTraceId ?? null],
        olderTimestamp: [(s) => [s.neighbors], (neighbors) => neighbors?.olderTimestamp ?? null],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.traceId],
            (traceId): SidePanelSceneContext => {
                // Discussions are always at the trace level, accessible from anywhere in the trace
                return {
                    activity_scope: ActivityScope.LLM_TRACE,
                    activity_item_id: traceId || '',
                    discussions_disabled: false,
                    activity_item_context: { trace_id: traceId || '' },
                }
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        initializeMessageStates: ({ inputCount, outputCount }) => {
            // Apply display option when initializing
            const displayOption = values.displayOption
            const inputStates = Array.from({ length: inputCount }, (_, i) => {
                if (displayOption === DisplayOption.ExpandAll) {
                    return true
                }
                // For collapse except output and last input, only show last input
                return i === inputCount - 1
            })
            const outputStates = Array.from({ length: outputCount }, () => true)

            // Update the states directly
            actions.applySearchResults(inputStates, outputStates)
        },
        setSearchQuery: ({ searchQuery }) => {
            // Only update URL if the search query actually changed
            // This prevents infinite loop when setSearchQuery is called from urlToAction
            const currentUrl = window.location.search
            const urlParams = new URLSearchParams(currentUrl)
            const currentSearchInUrl = urlParams.get('search') || ''

            if (searchQuery !== currentSearchInUrl) {
                // Update the URL with the search query
                const { traceId, eventId, dateRange } = values
                if (traceId) {
                    const params: any = {}
                    if (eventId) {
                        params.event = eventId
                    }
                    if (dateRange) {
                        if (dateRange.dateFrom && !dateRange.dateTo) {
                            params.timestamp = dateRange.dateFrom
                        } else if (dateRange.dateFrom && dateRange.dateTo) {
                            params.exception_ts = dayjs(dateRange.dateFrom)
                                .add(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes')
                                .toISOString()
                        }
                    }
                    if (searchQuery) {
                        params.search = searchQuery
                    }

                    // Use router to update URL
                    router.actions.replace(urls.aiObservabilityTrace(traceId, params))
                }
            }
        },
        copyLinePermalink: ({ lineNumber }) => {
            // Copy permalink to clipboard with line number in URL
            const url = new URL(window.location.href)
            url.searchParams.set('line', lineNumber.toString())
            copyToClipboard(url.toString(), 'permalink')
        },
    })),

    subscriptions(({ actions }) => ({
        traceId: (traceId: string) => {
            if (traceId) {
                actions.loadCommentCount()

                // Mark both tasks as completed - viewing a trace implies AI events were sent
                globalSetupLogic
                    .findMounted()
                    ?.actions.markTaskAsCompleted([SetupTaskId.IngestFirstLlmEvent, SetupTaskId.ViewFirstTrace])
            }
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.aiObservabilityTrace(':id')]: ({ id }, { event, timestamp, exception_ts, search, line, tab, msg }) => {
            actions.setTraceId(id ?? '')
            void addProductIntent({
                product_type: ProductKey.AI_OBSERVABILITY,
                intent_context: ProductIntentContext.LLM_ANALYTICS_TRACE_VIEWED,
            })
            actions.setEventId(event || null)
            const parsedMsg = msg ? parseInt(msg, 10) : NaN
            actions.setHighlightMessageIndex(!isNaN(parsedMsg) ? parsedMsg : null)
            const parsedLine = line ? parseInt(line, 10) : NaN
            actions.setLineNumber(!isNaN(parsedLine) ? parsedLine : null)
            actions.setInitialTab(tab || null)
            if (timestamp) {
                actions.setDateRange(timestamp || null)
            } else if (exception_ts) {
                // Increase the lookup window to 20 minutes before and after the exception timestamp, which gives in total 60 minutes.
                const parsedDate = dayjs(exception_ts)
                actions.setDateRange(
                    parsedDate.subtract(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes').toISOString(),
                    parsedDate.add(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes').toISOString()
                )
            }
            // Set search from URL param if provided, otherwise clear it
            actions.setSearchQuery(search || '')
        },
    })),

    trackedActionToUrl(({ values }) => {
        const buildUrl = (): string | undefined => {
            if (!values.traceId) {
                return undefined
            }
            const params: Record<string, unknown> = { ...router.values.searchParams }
            if (values.eventId) {
                params.event = values.eventId
            }
            if (values.dateRange) {
                if (values.dateRange.dateFrom && !values.dateRange.dateTo) {
                    params.timestamp = values.dateRange.dateFrom
                } else if (values.dateRange.dateFrom && values.dateRange.dateTo) {
                    params.exception_ts = dayjs(values.dateRange.dateFrom)
                        .add(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes')
                        .toISOString()
                }
            }
            if (values.searchQuery) {
                params.search = values.searchQuery
            }
            if (values.lineNumber) {
                params.line = values.lineNumber.toString()
            }
            // Always include tab parameter
            params.tab = values.viewMode
            return urls.aiObservabilityTrace(values.traceId, params)
        }

        return {
            setViewMode: buildUrl,
        }
    }),
])
