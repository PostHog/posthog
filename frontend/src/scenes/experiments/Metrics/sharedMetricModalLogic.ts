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

/**
 * A quick-select intent captured when the user clicks "All" or a tag button. We can't apply it
 * immediately because matching metrics may live on pages that haven't been fetched yet — so we
 * stash the intent, load every remaining page, then resolve it against the full set.
 */
export type QuickSelect = {
    /** `null` means "all compatible metrics"; otherwise only metrics carrying this tag. */
    tag: string | null
    /** Metric ids already on the experiment — never selectable, so excluded from the result. */
    excludeIds: SharedMetric['id'][]
}

const resolveQuickSelect = (metrics: SharedMetric[], { tag, excludeIds }: QuickSelect): SharedMetric['id'][] => {
    const excluded = new Set(excludeIds)
    return metrics
        .filter((metric) => !excluded.has(metric.id))
        .filter((metric) => tag === null || (metric.tags?.includes(tag) ?? false))
        .map((metric) => metric.id)
}

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
        toggleMetricSelected: (id: SharedMetric['id']) => ({ id }),
        clearSelectedMetricIds: true,
        // Quick-select "All" / by-tag — both load every remaining page before resolving the selection.
        selectAllMetrics: (excludeIds: SharedMetric['id'][]) => ({ excludeIds }),
        selectMetricsByTag: (tag: string, excludeIds: SharedMetric['id'][]) => ({ tag, excludeIds }),
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
                toggleMetricSelected: (state, { id }) =>
                    state.includes(id) ? state.filter((existing) => existing !== id) : [...state, id],
                clearSelectedMetricIds: () => [],
                openSharedMetricModal: () => [],
                closeSharedMetricModal: () => [],
            },
        ],
        // Set when a quick-select needs more pages; consumed once loadAllSharedMetrics finishes.
        pendingQuickSelect: [
            null as QuickSelect | null,
            {
                selectAllMetrics: (_, { excludeIds }) => ({ tag: null, excludeIds }),
                selectMetricsByTag: (_, { tag, excludeIds }) => ({ tag, excludeIds }),
                setSelectedMetricIds: () => null,
                clearSelectedMetricIds: () => null,
                openSharedMetricModal: () => null,
                closeSharedMetricModal: () => null,
                setSearchTerm: () => null,
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
                // Walk every remaining page so quick-select by tag / "All" sees the full set, not just
                // the rows already rendered. This is the "keep clicking Load more until done" mechanism.
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
                    const results = [...response.results]
                    let next = response.next
                    while (next) {
                        const page: CountedPaginatedResponse<SharedMetric> = await api.get(next)
                        // Abort if a concurrent load (e.g. a new search) superseded this run.
                        breakpoint()
                        results.push(...page.results)
                        next = page.next ?? null
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
        // A quick-select either resolves immediately (everything already loaded) or kicks off a
        // full load, with loadAllSharedMetricsSuccess resolving the stashed intent afterwards.
        const startQuickSelect = (): void => {
            if (!values.pendingQuickSelect) {
                return
            }
            // Resolve immediately only when every page is already loaded; otherwise fetch the rest first.
            if (values.canLoadMore || !values.sharedMetricsResponse) {
                actions.loadAllSharedMetrics(null)
                return
            }
            actions.setSelectedMetricIds(resolveQuickSelect(values.compatibleSharedMetrics, values.pendingQuickSelect))
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
            selectAllMetrics: startQuickSelect,
            selectMetricsByTag: startQuickSelect,
            loadAllSharedMetricsSuccess: () => {
                if (values.pendingQuickSelect) {
                    actions.setSelectedMetricIds(
                        resolveQuickSelect(values.compatibleSharedMetrics, values.pendingQuickSelect)
                    )
                }
            },
        }
    }),
])
