import { lemonToast } from '@posthog/lemon-ui'
import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType, InsightModel, InsightShortId } from '~/types'

import type { addInsightFromDashboardModalLogicType } from './addInsightFromDashboardModalLogicType'

export interface AddInsightFromDashboardModalLogicProps {
    dashboard: DashboardType
    insight?: Partial<InsightModel>
}

export interface Fuse extends FuseClass<any> {}

export const addInsightFromDashboardModalLogic = kea<addInsightFromDashboardModalLogicType>([
    props({} as AddInsightFromDashboardModalLogicProps),
    key(({ dashboard, insight }) => {
        if (!dashboard.id) {
            throw Error('must provide a dashboard id')
        }
        return `${dashboard.id}/${insight?.short_id}`
    }),
    path(['lib', 'components', 'AddInsightFromDashboard', 'saveInsightFromDashboardModalLogic']),
    connect((props: AddInsightFromDashboardModalLogicProps) => ({
        actions: [
            dashboardLogic({ id: props.dashboard.id }),
            ['refreshAllDashboardItems'],
            eventUsageLogic,
            ['reportSavedInsightToDashboard', 'reportRemovedInsightFromDashboard'],
            insightLogic({ dashboardItemId: props?.insight?.short_id, cachedInsight: props?.insight }),
            ['updateInsight'],
        ],
        values: [savedInsightsLogic, ['insights']],
    })),
    actions({
        addNewInsight: true,
        setInsightId: (short_id: InsightShortId) => ({ short_id }),
        setSearchQuery: (query: string) => ({ query }),
        setScrollIndex: (index: number) => ({ index }),
        addToDashboard: true,
        removeFromDashboard: true,
    }),
    reducers(() => ({
        _insightId: ['', { setInsightId: (_, { short_id }) => short_id }],
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        scrollIndex: [-1 as number, { setScrollIndex: (_, { index }) => index }],
    })),
    selectors({
        insightId: [(s) => [s._insightId], (_insightId) => _insightId],
        insightsFuse: [
            () => [savedInsightsLogic.selectors.insights],
            (insights): Fuse => {
                return new FuseClass(insights.results || [], {
                    keys: ['name', 'description', 'tags'],
                    threshold: 0.3,
                })
            },
        ],
        filteredInsights: [
            (s) => [s.searchQuery, s.insightsFuse, savedInsightsLogic.selectors.insights],
            (searchQuery, insightsFuse, insights): InsightModel[] =>
                searchQuery.length
                    ? insightsFuse.search(searchQuery).map((r: FuseClass.FuseResult<InsightModel>) => r.item)
                    : insights.results,
        ],
    }),
    listeners(({ props, actions }) => ({
        addToDashboard: async (): Promise<void> => {
            actions.updateInsight(
                { ...props.insight, dashboards: [...(props?.insight?.dashboards || []), props.dashboard.id] },
                () => {
                    actions.reportSavedInsightToDashboard()
                    dashboardsModel.actions.tileAddedToDashboard(props.dashboard.id)
                    lemonToast.success('Insight added to dashboard')
                }
            )
        },
        removeFromDashboard: async (): Promise<void> => {
            actions.updateInsight(
                {
                    ...props.insight,
                    dashboards: (props?.insight?.dashboards || []).filter((d) => d !== props.dashboard.id),
                    dashboard_tiles: (props?.insight?.dashboard_tiles || []).filter(
                        (dt) => dt.dashboard_id !== props.dashboard.id
                    ),
                },
                () => {
                    actions.reportRemovedInsightFromDashboard()
                    lemonToast.success('Insight removed from dashboard')
                }
            )
        },
    })),
])
