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
        },
    })),
])
