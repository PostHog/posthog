import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { objectsEqual, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'

import { cleanFilters, InsightsResult, SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

import type { eventInsightsLogicType } from './eventInsightsLogicType'

export const INSIGHTS_PER_PAGE = 10

export const eventInsightsLogic = kea<eventInsightsLogicType>([
    path(['scenes', 'data-management', 'events', 'eventInsightsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
        logic: [eventUsageLogic],
    })),
    actions({
        setFilters: (filters: Partial<SavedInsightFilters>) => ({ filters }),
        loadInsights: true,
        setPage: (page: number) => ({ page }),
    }),
    loaders(({ values }) => ({
        insights: {
            __default: { results: [], count: 0, filters: null, offset: 0 } as InsightsResult,
            loadInsights: async () => {
                const { filters } = values
                const { order, page, events, search } = filters

                if (!events || events.length === 0) {
                    return {
                        results: [],
                        count: 0,
                        filters,
                        offset: 0,
                    } as InsightsResult
                }

                const params: Record<string, any> = {
                    order,
                    events,
                    limit: INSIGHTS_PER_PAGE,
                    offset: Math.max(0, (page - 1) * INSIGHTS_PER_PAGE),
                    saved: true,
                    basic: true,
                }

                if (search) {
                    params.search = search
                }

                const response = await api.get(
                    `api/environments/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`
                )

                return {
                    ...response,
                    filters,
                    results: response.results.map((rawInsight: any) => getQueryBasedInsightModel(rawInsight)),
                } as InsightsResult
            },
        },
    })),
    reducers({
        rawFilters: [
            null as Partial<SavedInsightFilters> | null,
            {
                setFilters: (state, { filters }) => {
                    return cleanFilters({
                        ...state,
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    })
                },
            },
        ],
    }),
    selectors({
        filters: [(s) => [s.rawFilters], (rawFilters: object): SavedInsightFilters => cleanFilters(rawFilters || {})],
        count: [(s) => [s.insights], (insights) => insights.count],
        sorting: [
            (s) => [s.filters],
            (filters): Sorting | null =>
                filters.order
                    ? filters.order.startsWith('-')
                        ? { columnKey: filters.order.slice(1), order: -1 }
                        : { columnKey: filters.order, order: 1 }
                    : null,
        ],
        page: [(s) => [s.filters], (filters) => filters.page],
        usingFilters: [
            (s) => [s.filters],
            (filters) => !objectsEqual(cleanFilters({ ...filters, events: undefined }), cleanFilters({})),
        ],
    }),
    listeners(({ actions, values, selectors }) => ({
        setPage: async ({ page }) => {
            actions.setFilters({ page })
            actions.loadInsights()
        },
        setFilters: async ({}, breakpoint, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const newFilters = values.filters
            await breakpoint(300)
            if (!objectsEqual(oldFilters, newFilters) && newFilters.events && newFilters.events.length > 0) {
                actions.loadInsights()
            }
        },
    })),
])
