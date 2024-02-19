import { PaginationManual } from '@posthog/lemon-ui'
import FuseClass from 'fuse.js'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { InsightsResult } from 'scenes/saved-insights/savedInsightsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { InsightModel, InsightShortId } from '~/types'

import type { addInsightsToDashboardModalLogicType } from './addInsightsToDashboardModalLogicType'

export interface AddInsightsToDashboardModalLogicProps {
    dashboardId?: number
}

const INSIGHTS_PER_PAGE = 10

export interface Fuse extends FuseClass<any> {}

export const addInsightsToDashboardModalLogic = kea<addInsightsToDashboardModalLogicType>([
    props({} as AddInsightsToDashboardModalLogicProps),
    key(({ dashboardId }) => {
        return dashboardId || 'new'
    }),
    path((key) => ['lib', 'components', 'AddInsightsToDashboard', 'addInsightsToDashboardModalLogic', key]),
    connect((props: AddInsightsToDashboardModalLogicProps) => ({
        actions: [
            dashboardLogic({ id: props.dashboardId }),
            ['addInsight', 'removeTile'],
            eventUsageLogic,
            ['reportSavedInsightToDashboard', 'reportRemovedInsightFromDashboard'],
            dashboardsModel,
            ['tileRemovedFromDashboard', 'tileAddedToDashboard'],
        ],
        values: [dashboardLogic({ id: props.dashboardId }), ['tiles', 'dashboard']],
    })),
    loaders(({ values }) => ({
        insights: {
            __default: { results: [], count: 0, filters: null, offset: 0 } as InsightsResult,
            loadInsights: async () => {
                const params = {
                    order: '-last_modified_at',
                    limit: INSIGHTS_PER_PAGE,
                    ...((values.searchQuery == '' || values.page > 1) && {
                        offset: Math.max(0, (values.page - 1) * INSIGHTS_PER_PAGE),
                    }),
                    saved: true,
                    ...(values.searchQuery != '' && { search: values.searchQuery }),
                    basic: true,
                    include_query_insights: true,
                }

                return await api.get(`api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`)
            },
        },
    })),
    actions({
        setSearchQuery: (query: string) => ({ query }),
        setScrollIndex: (index: number) => ({ index }),
        setPage: (page: number) => ({ page }),
        addToDashboard: (insight: InsightModel) => ({ insight }),
        removeFromDashboard: (insight: InsightModel) => ({ insight }),
    }),
    reducers(({ props }) => ({
        page: [1, { setPage: (_, { page }) => page }],
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        scrollIndex: [-1 as number, { setScrollIndex: (_, { index }) => index }],
        insightWithActiveAPICall: [
            null as InsightShortId | null,
            {
                addToDashboard: (_, { insight }) => insight?.short_id || null,
                removeFromDashboard: (_, { insight }) => insight?.short_id || null,
                tileRemovedFromDashboard: (curr, { dashboardId }) => (dashboardId === props.dashboardId ? null : curr),
                tileAddedToDashboard: (curr, { dashboardId }) => (dashboardId === props.dashboardId ? null : curr),
            },
        ],
    })),
    selectors(({ actions }) => ({
        pagination: [
            (s) => [s.page, s.insights],
            (page, insights): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: INSIGHTS_PER_PAGE,
                    currentPage: page,
                    entryCount: insights.count,
                    onBackward: () => actions.setPage(page - 1),
                    onForward: () => actions.setPage(page + 1),
                }
            },
        ],
    })),
    listeners(({ props, actions, values }) => ({
        addToDashboard: async ({ insight }) => {
            if (!props.dashboardId) {
                return
            }

            if (insight.dashboards) {
                insight.dashboards = [...insight.dashboards, props.dashboardId]
            } else {
                insight.dashboards = [props.dashboardId]
            }

            actions.addInsight(insight)
        },
        removeFromDashboard: async ({ insight }) => {
            const tile = values.tiles.find((tile) => tile?.insight?.short_id === insight.short_id)
            if (!tile) {
                return
            }
            actions.removeTile(tile)
        },
        setPage: async () => {
            actions.loadInsights()
        },
        setSearchQuery: async () => {
            actions.loadInsights()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadInsights()
    }),
])
