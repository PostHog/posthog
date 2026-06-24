import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { CountedPaginatedResponse } from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { toParams } from 'lib/utils/url'
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
        // Click a tag to select (and show) every metric carrying it, loading any unloaded pages first.
        selectByTag: (tag: string, alreadyAddedIds: SharedMetric['id'][]) => ({ tag, alreadyAddedIds }),
        clearFilterTags: true,
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
        // The active tags used both to filter the table and to drive tag-based selection.
        // Tags are additive toggles: clicking a tag activates it, clicking it again deactivates it.
        filterTags: [
            [] as string[],
            {
                selectByTag: (state, { tag }) =>
                    state.includes(tag) ? state.filter((existingTag) => existingTag !== tag) : [...state, tag],
                clearFilterTags: () => [],
                setSearchTerm: () => [],
                openSharedMetricModal: () => [],
                closeSharedMetricModal: () => [],
            },
        ],
    }),

    loaders(({ values }) => ({
        sharedMetricsResponse: [
            null as CountedPaginatedResponse<SharedMetric> | null,
            {
                loadSharedMetrics: async (_: void, breakpoint) => {
                    const params = toParams({
                        limit: MODAL_PAGE_SIZE,
                        offset: 0,
                        search: values.searchTerm || undefined,
                    })
                    const response = (await api.get(
                        `api/projects/${values.currentProjectId}/experiment_saved_metrics?${params}`
                    )) as CountedPaginatedResponse<SharedMetric>
                    // Discard stale responses that resolve after a newer search has fired
                    breakpoint()
                    return response
                },
                // Page through every remaining result so the tag filter and tag chip list cover the
                // whole set of shared metrics, not just the first page rendered in the table.
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
                    const results = [...(response.results ?? [])]
                    let next = response.next
                    while (next) {
                        const page: CountedPaginatedResponse<SharedMetric> = await api.get(next)
                        // Abort if a concurrent loadSharedMetrics (e.g. a new search) superseded this load.
                        breakpoint()
                        results.push(...page.results)
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
        // Every tag present across the loaded compatible metrics — shown as filter chips.
        availableTags: [
            (s) => [s.compatibleSharedMetrics],
            (compatibleSharedMetrics: SharedMetric[]): string[] =>
                Array.from(
                    new Set(compatibleSharedMetrics.flatMap((metric) => metric.tags ?? []).filter(Boolean))
                ).sort(),
        ],
        // The metrics actually rendered: filtered to the chosen tags when any are active.
        displayedMetrics: [
            (s) => [s.compatibleSharedMetrics, s.filterTags],
            (compatibleSharedMetrics: SharedMetric[], filterTags: string[]): SharedMetric[] =>
                filterTags.length === 0
                    ? compatibleSharedMetrics
                    : compatibleSharedMetrics.filter((metric) => metric.tags?.some((tag) => filterTags.includes(tag))),
        ],
        // True while the remaining pages are still being fetched in the background.
        isLoadingAllSharedMetrics: [
            (s) => [s.sharedMetricsResponseLoading, s.sharedMetricsResponse],
            (sharedMetricsResponseLoading: boolean, response: CountedPaginatedResponse<SharedMetric> | null): boolean =>
                sharedMetricsResponseLoading || !!response?.next,
        ],
        isCreateMode: [(s) => [s.isEditMode], (isEditMode: boolean) => !isEditMode],
    }),

    listeners(({ actions, values }) => ({
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
            // Eagerly pull in the rest of the pages so the tag list and tag selection cover every metric.
            if (values.sharedMetricsResponse?.next) {
                actions.loadAllSharedMetrics(null)
            }
        },
        // Additive toggle: clicking a tag selects its metrics, clicking it again deselects them.
        // The tag buttons stay disabled until the full load finishes, so every page is available here.
        selectByTag: ({ tag, alreadyAddedIds }) => {
            const alreadyAdded = new Set(alreadyAddedIds)
            const tagMetricIds = values.compatibleSharedMetrics
                .filter((metric) => !alreadyAdded.has(metric.id) && metric.tags?.includes(tag))
                .map((metric) => metric.id)

            // filterTags already reflects the toggle: present → just activated, absent → just deactivated.
            if (values.filterTags.includes(tag)) {
                actions.setSelectedMetricIds(Array.from(new Set([...values.selectedMetricIds, ...tagMetricIds])))
                return
            }
            // Deactivated: drop this tag's metrics unless another active tag still covers them.
            const activeTags = new Set(values.filterTags)
            const removableIds = new Set(
                values.compatibleSharedMetrics
                    .filter(
                        (metric) => metric.tags?.includes(tag) && !metric.tags?.some((other) => activeTags.has(other))
                    )
                    .map((metric) => metric.id)
            )
            actions.setSelectedMetricIds(values.selectedMetricIds.filter((id) => !removableIds.has(id)))
        },
    })),
])
