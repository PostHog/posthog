import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { CountedPaginatedResponse } from 'lib/api'
import { toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { NodeKind } from '~/queries/schema/schema-general'

import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'
import { METRIC_CONTEXTS, type MetricContext } from './experimentMetricModalLogic'
import type { sharedMetricModalLogicType } from './sharedMetricModalLogicType'

export const MODAL_PAGE_SIZE = 20

export const sharedMetricModalLogic = kea<sharedMetricModalLogicType>([
    path(['scenes', 'experiments', 'Metrics', 'sharedMetricModalLogic']),

    connect(() => ({
        actions: [eventUsageLogic, ['reportExperimentSharedMetricAssigned']],
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        openSharedMetricModal: (context: MetricContext, sharedMetricId?: SharedMetric['id'] | null) => ({
            context,
            sharedMetricId,
        }),
        closeSharedMetricModal: true,
        setSharedMetric: (sharedMetric: SharedMetric) => ({ sharedMetric }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setHasAnyCompatibleSharedMetrics: (hasAny: boolean) => ({ hasAny }),
        setSelectedMetricIds: (ids: SharedMetric['id'][]) => ({ ids }),
        toggleSelectedMetricId: (id: SharedMetric['id']) => ({ id }),
        clearSelectedMetricIds: true,
        // Quick-select across the whole result set, not just the pages already loaded.
        selectAllSelectableMetrics: (alreadyAddedIds: SharedMetric['id'][]) => ({ alreadyAddedIds }),
        selectMetricsByTag: (tag: string, alreadyAddedIds: SharedMetric['id'][]) => ({ tag, alreadyAddedIds }),
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openSharedMetricModal: () => true,
                closeSharedMetricModal: () => false,
            },
        ],
        sharedMetricId: [
            null as SharedMetric['id'] | null,
            {
                openSharedMetricModal: (_, { sharedMetricId }) => sharedMetricId ?? null,
                closeSharedMetricModal: () => null,
            },
        ],
        context: [
            METRIC_CONTEXTS.primary as MetricContext,
            {
                openSharedMetricModal: (_, { context }) => context,
                closeSharedMetricModal: () => METRIC_CONTEXTS.primary,
            },
        ],
        isEditMode: [
            false,
            {
                openSharedMetricModal: (_, { sharedMetricId }) => !!sharedMetricId,
                closeSharedMetricModal: () => false,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                openSharedMetricModal: () => '',
                closeSharedMetricModal: () => '',
            },
        ],
        // Whether the experiment has any compatible shared metrics at all, captured from the
        // unfiltered (empty-search) load — so a search returning zero does not flip it to false.
        hasAnyCompatibleSharedMetrics: [
            false,
            {
                setHasAnyCompatibleSharedMetrics: (_, { hasAny }) => hasAny,
                openSharedMetricModal: () => false,
            },
        ],
        selectedMetricIds: [
            [] as SharedMetric['id'][],
            {
                setSelectedMetricIds: (_, { ids }) => ids,
                toggleSelectedMetricId: (state, { id }) =>
                    state.includes(id) ? state.filter((existingId) => existingId !== id) : [...state, id],
                clearSelectedMetricIds: () => [],
                openSharedMetricModal: () => [],
                closeSharedMetricModal: () => [],
            },
        ],
        // A pending quick-select intent kept while the remaining pages load, applied once
        // every page is in memory so the selection covers metrics beyond the first page.
        pendingQuickSelect: [
            null as { tag: string | null; alreadyAddedIds: SharedMetric['id'][] } | null,
            {
                selectAllSelectableMetrics: (_, { alreadyAddedIds }) => ({ tag: null, alreadyAddedIds }),
                selectMetricsByTag: (_, { tag, alreadyAddedIds }) => ({ tag, alreadyAddedIds }),
                setSelectedMetricIds: () => null,
                openSharedMetricModal: () => null,
                closeSharedMetricModal: () => null,
            },
        ],
    }),

    loaders(({ values }) => ({
        sharedMetricsResponse: [
            null as CountedPaginatedResponse<SharedMetric> | null,
            {
                loadSharedMetrics: async () => {
                    const params = toParams({
                        limit: MODAL_PAGE_SIZE,
                        offset: 0,
                        search: values.searchTerm || undefined,
                    })
                    return (await api.get(
                        `api/projects/${values.currentProjectId}/experiment_saved_metrics?${params}`
                    )) as CountedPaginatedResponse<SharedMetric>
                },
                loadNextSharedMetrics: async (_, breakpoint) => {
                    const next = values.sharedMetricsResponse?.next
                    if (!next) {
                        return values.sharedMetricsResponse
                    }
                    const baseResults = values.sharedMetricsResponse?.results ?? []
                    const response: CountedPaginatedResponse<SharedMetric> = await api.get(next)
                    // Abort if a concurrent loadSharedMetrics (e.g. a new search) superseded this page request.
                    breakpoint()
                    return {
                        ...response,
                        results: [...baseResults, ...response.results],
                    }
                },
                // Page through every remaining result so quick-select-by-tag operates on the full
                // set, not just the rows currently rendered in the table.
                loadAllSharedMetrics: async (_, breakpoint) => {
                    let response = values.sharedMetricsResponse
                    if (!response) {
                        const params = toParams({
                            limit: MODAL_PAGE_SIZE,
                            offset: 0,
                            search: values.searchTerm || undefined,
                        })
                        response = (await api.get(
                            `api/projects/${values.currentProjectId}/experiment_saved_metrics?${params}`
                        )) as CountedPaginatedResponse<SharedMetric>
                        breakpoint()
                    }
                    let results = [...(response.results ?? [])]
                    let next = response.next
                    while (next) {
                        const page: CountedPaginatedResponse<SharedMetric> = await api.get(next)
                        breakpoint()
                        results = [...results, ...page.results]
                        next = page.next
                        response = page
                    }
                    return { ...response, results, next: null }
                },
            },
        ],
    })),

    selectors({
        loadedSharedMetrics: [(s) => [s.sharedMetricsResponse], (response): SharedMetric[] => response?.results ?? []],
        compatibleSharedMetrics: [
            (s) => [s.loadedSharedMetrics],
            (loadedSharedMetrics: SharedMetric[]): SharedMetric[] =>
                loadedSharedMetrics.filter((metric) => metric.query.kind === NodeKind.ExperimentMetric),
        ],
        canLoadMore: [(s) => [s.sharedMetricsResponse], (response): boolean => !!response?.next],
        isCreateMode: [(s) => [s.isEditMode], (isEditMode: boolean) => !isEditMode],
    }),

    listeners(({ actions, values }) => {
        // Apply a queued quick-select once every page is loaded, so the selection spans
        // all metrics matching the tag rather than only the rows already rendered.
        const applyPendingQuickSelect = (): void => {
            const pending = values.pendingQuickSelect
            if (!pending) {
                return
            }
            const alreadyAdded = new Set(pending.alreadyAddedIds)
            const selectable = values.compatibleSharedMetrics.filter((metric) => !alreadyAdded.has(metric.id))
            const matched =
                pending.tag === null
                    ? selectable
                    : selectable.filter((metric) => metric.tags?.includes(pending.tag as string))
            actions.setSelectedMetricIds(matched.map((metric) => metric.id))
        }
        const startQuickSelect = (): void => {
            if (values.canLoadMore) {
                actions.loadAllSharedMetrics()
                return
            }
            applyPendingQuickSelect()
        }
        return {
            openSharedMetricModal: () => {
                actions.loadSharedMetrics()
            },
            setSearchTerm: async (_, breakpoint) => {
                await breakpoint(300)
                actions.loadSharedMetrics()
            },
            loadSharedMetricsSuccess: () => {
                // Only the unfiltered load establishes the baseline "are there any compatible metrics" answer.
                if (!values.searchTerm) {
                    actions.setHasAnyCompatibleSharedMetrics(values.compatibleSharedMetrics.length > 0)
                }
            },
            selectAllSelectableMetrics: () => {
                startQuickSelect()
            },
            selectMetricsByTag: () => {
                startQuickSelect()
            },
            loadAllSharedMetricsSuccess: () => {
                applyPendingQuickSelect()
            },
        }
    }),
])
