import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType, InsightModel, InsightShortId } from '~/types'

import type { addInsightsToDashboardModalLogicType } from './addInsightsToDashboardModalLogicType'

export interface AddInsightsToDashboardModalLogicProps {
    dashboard: DashboardType
}

export interface Fuse extends FuseClass<any> {}

export const addInsightsToDashboardModalLogic = kea<addInsightsToDashboardModalLogicType>([
    props({} as AddInsightsToDashboardModalLogicProps),
    key(({ dashboard }) => {
        if (!dashboard.id) {
            throw Error('must provide a dashboard id')
        }
        return dashboard.id
    }),
    path(['lib', 'components', 'AddInsightsToDashboard', 'saveInsightsToDashboardModalLogic']),
    connect((props: AddInsightsToDashboardModalLogicProps) => ({
        actions: [
            dashboardLogic({ id: props.dashboard.id }),
            ['addInsight', 'removeTile', 'refreshAllDashboardItems'],
            eventUsageLogic,
            ['reportSavedInsightToDashboard', 'reportRemovedInsightFromDashboard'],
            dashboardsModel,
            ['tileRemovedFromDashboard', 'tileAddedToDashboard'],
        ],
        values: [savedInsightsLogic, ['insights'], dashboardLogic({ id: props.dashboard.id }), ['tiles']],
    })),
    actions({
        addNewInsight: true,
        setInsightId: (short_id: InsightShortId) => ({ short_id }),
        setSearchQuery: (query: string) => ({ query }),
        setScrollIndex: (index: number) => ({ index }),
        addToDashboard: (insight: InsightModel) => ({ insight }),
        removeFromDashboard: (insight: InsightModel) => ({ insight }),
    }),
    reducers(({ props }) => ({
        _insightId: ['', { setInsightId: (_, { short_id }) => short_id }],
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        scrollIndex: [-1 as number, { setScrollIndex: (_, { index }) => index }],
        insightWithActiveAPICall: [
            null as InsightShortId | null,
            {
                addToDashboard: (_, { insight }) => insight?.short_id || null,
                removeFromDashboard: (_, { insight }) => insight?.short_id || null,
                tileRemovedFromDashboard: (curr, { dashboardId }) => (dashboardId === props.dashboard.id ? null : curr),
                tileAddedToDashboard: (curr, { dashboardId }) => (dashboardId === props.dashboard.id ? null : curr),
            },
        ],
    })),
    selectors({
        insightId: [(s) => [s._insightId], (_insightId) => _insightId],
        insightsFuse: [
            (s) => [s.insights],
            (insights): Fuse => {
                return new FuseClass(insights.results || [], {
                    keys: ['name', 'description', 'tags'],
                    threshold: 0.3,
                })
            },
        ],
        filteredInsights: [
            (s) => [s.searchQuery, s.insightsFuse, s.insights],
            (searchQuery, insightsFuse, insights): InsightModel[] =>
                searchQuery.length
                    ? insightsFuse.search(searchQuery).map((r: FuseClass.FuseResult<InsightModel>) => r.item)
                    : insights.results,
        ],
    }),
    listeners(({ props, actions, values }) => ({
        addToDashboard: async ({ insight }) => {
            if (insight.dashboards) {
                insight.dashboards = [...insight.dashboards, props.dashboard.id]
            } else {
                insight.dashboards = [props.dashboard.id]
            }

            actions.addInsight(insight, () => {
                actions.reportSavedInsightToDashboard()
            })
        },
        removeFromDashboard: async ({ insight }) => {
            const tile = values.tiles.find((tile) => tile?.insight?.short_id === insight.short_id)
            if (!tile) {
                return
            }
            actions.removeTile(tile, () => {
                actions.reportRemovedInsightFromDashboard()
            })
        },
    })),
])
