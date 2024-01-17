import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType, InsightModel, InsightShortId } from '~/types'

import type { addInsightFromDashboardModalLogicType } from './addInsightFromDashboardModalLogicType'

export interface AddInsightFromDashboardModalLogicProps {
    dashboard: DashboardType
}

export interface Fuse extends FuseClass<any> {}

export const addInsightFromDashboardModalLogic = kea<addInsightFromDashboardModalLogicType>([
    props({} as AddInsightFromDashboardModalLogicProps),
    key(({ dashboard }) => {
        if (!dashboard.id) {
            throw Error('must provide a dashboard id')
        }
        return dashboard.id
    }),
    path(['lib', 'components', 'AddInsightFromDashboard', 'saveInsightFromDashboardModalLogic']),
    connect((props: AddInsightFromDashboardModalLogicProps) => ({
        actions: [
            dashboardLogic({ id: props.dashboard.id }),
            ['addInsightTile', 'removeTile', 'loadDashboardItemsSuccess'],
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
                addToDashboard: (_, { insight }) => insight.short_id,
                removeFromDashboard: (_, { insight }) => insight.short_id,
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
            // Tricky: update insight to include dashboard from dashboard uses api's deprecated dashboads field
            if (insight.dashboards) {
                insight.dashboards = [...insight.dashboards, props.dashboard.id]
            } else {
                insight.dashboards = [props.dashboard.id]
            }

            actions.addInsightTile(insight, () => {
                dashboardsModel.actions.tileAddedToDashboard(props.dashboard.id)
                actions.reportSavedInsightToDashboard()
            })
        },
        removeFromDashboard: async ({ insight }) => {
            const tile = values.tiles.find((tile) => tile?.insight?.short_id === insight.short_id)
            if (!tile) {
                return
            }
            actions.removeTile(tile, () => {
                dashboardsModel.actions.tileRemovedFromDashboard({
                    tile: tile,
                    dashboardId: props.dashboard.id,
                })
                actions.reportRemovedInsightFromDashboard()
            })
        },
    })),
])
