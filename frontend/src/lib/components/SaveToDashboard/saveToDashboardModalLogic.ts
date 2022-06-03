import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import type { saveToDashboardModalLogicType } from './saveToDashboardModalLogicType'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { DashboardType, InsightModel, InsightType } from '~/types'
import FuseClass from 'fuse.js'
import { lemonToast } from 'lib/components/lemonToast'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { insightLogic } from 'scenes/insights/insightLogic'

export interface SaveToDashboardModalLogicProps {
    insight: Partial<InsightModel>
    fromDashboard?: number
}

// Helping kea-typegen navigate the exported default class for Fuse
// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface Fuse extends FuseClass<any> {}

export const saveToDashboardModalLogic = kea<saveToDashboardModalLogicType>({
    path: ['lib', 'components', 'SaveToDashboard', 'saveToDashboardModalLogic'],
    props: {} as SaveToDashboardModalLogicProps,
    key: ({ insight }) => {
        if (!insight.short_id) {
            throw Error('must provide an insight with a short id')
        }
        return insight.short_id
    },
    connect: (props: SaveToDashboardModalLogicProps) => ({
        logic: [newDashboardLogic, dashboardsModel, prompt({ key: `saveToDashboardModalLogic-new-dashboard` })],
        actions: [
            insightLogic({ dashboardItemId: props.insight.short_id }),
            ['updateInsight', 'updateInsightSuccess', 'updateInsightFailure'],
            eventUsageLogic,
            ['reportSavedInsightToDashboard', 'reportRemovedInsightFromDashboard', 'reportCreatedDashboardFromModal'],
        ],
    }),
    actions: {
        addNewDashboard: true,
        setDashboardId: (id: number) => ({ id }),
        setSearchQuery: (query: string) => ({ query }),
        setInsight: (insight: InsightType) => ({ insight }),
        setScrollIndex: (index: number) => ({ index }),
        addToDashboard: (insight: Partial<InsightModel>, dashboardId: number) => ({ insight, dashboardId }),
        removeFromDashboard: (insight: Partial<InsightModel>, dashboardId: number) => ({ insight, dashboardId }),
    },

    reducers: {
        _dashboardId: [null as null | number, { setDashboardId: (_, { id }) => id }],
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        scrollIndex: [-1 as number, { setScrollIndex: (_, { index }) => index }],
        dashboardWithActiveAPICall: [
            null as number | null,
            {
                addToDashboard: (_, { dashboardId }) => dashboardId,
                removeFromDashboard: (_, { dashboardId }) => dashboardId,
                updateInsightSuccess: () => null,
                updateInsightFailure: () => null,
            },
        ],
    },

    selectors: {
        dashboardId: [
            (s) => [
                s._dashboardId,
                dashboardsModel.selectors.lastDashboardId,
                dashboardsModel.selectors.nameSortedDashboards,
                (_, props) => props.fromDashboard,
            ],
            (_dashboardId, lastDashboardId, dashboards, fromDashboard) =>
                _dashboardId || fromDashboard || lastDashboardId || (dashboards.length > 0 ? dashboards[0].id : null),
        ],
        dashboardsFuse: [
            () => [dashboardsModel.selectors.nameSortedDashboards],
            (nameSortedDashboards): Fuse => {
                return new FuseClass(nameSortedDashboards || [], {
                    keys: ['name', 'description', 'tags'],
                    threshold: 0.3,
                })
            },
        ],
        filteredDashboards: [
            (s) => [s.searchQuery, s.dashboardsFuse, dashboardsModel.selectors.nameSortedDashboards],
            (searchQuery, dashboardsFuse, nameSortedDashboards): DashboardType[] =>
                searchQuery.length
                    ? dashboardsFuse.search(searchQuery).map((r: FuseClass.FuseResult<DashboardType>) => r.item)
                    : nameSortedDashboards,
        ],
        currentDashboards: [
            (s) => [s.filteredDashboards, (_, props) => props.insight],
            (filteredDashboards, insight): DashboardType[] =>
                filteredDashboards.filter((d: DashboardType) => insight.dashboards?.includes(d.id)),
        ],
        availableDashboards: [
            (s) => [s.filteredDashboards, (_, props) => props.insight],
            (filteredDashboards, insight): DashboardType[] =>
                filteredDashboards.filter((d: DashboardType) => !insight.dashboards?.includes(d.id)),
        ],
        orderedDashboards: [
            (s) => [s.currentDashboards, s.availableDashboards],
            (currentDashboards, availableDashboards): DashboardType[] => [...currentDashboards, ...availableDashboards],
        ],
    },

    listeners: ({ actions, values, props }) => ({
        setDashboardId: ({ id }) => {
            dashboardsModel.actions.setLastDashboardId(id)
        },

        addNewDashboard: async () => {
            prompt({ key: `saveToDashboardModalLogic-new-dashboard` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: (name: string) => newDashboardLogic.actions.addDashboard({ name, show: false }),
            })
        },

        [dashboardsModel.actionTypes.addDashboardSuccess]: async ({ dashboard }) => {
            actions.reportCreatedDashboardFromModal()
            actions.setDashboardId(dashboard.id)
            actions.addToDashboard(props.insight, dashboard.id)
            actions.setScrollIndex(values.orderedDashboards.findIndex((d) => d.id === dashboard.id))
        },

        addToDashboard: async ({ insight, dashboardId }) => {
            actions.updateInsight({ ...insight, dashboards: [...(insight.dashboards || []), dashboardId] }, () => {
                actions.reportSavedInsightToDashboard()
                lemonToast.success('Insight added to dashboard', {
                    button: {
                        label: 'View dashboard',
                        action: () => router.actions.push(urls.dashboard(dashboardId)),
                    },
                })
            })
        },
        removeFromDashboard: async ({ insight, dashboardId }): Promise<void> => {
            actions.updateInsight(
                {
                    ...insight,
                    dashboards: (insight.dashboards || []).filter((d) => d !== dashboardId),
                },
                () => {
                    actions.reportRemovedInsightFromDashboard()
                    lemonToast.success('Insight removed from dashboard')
                }
            )
        },
    }),
})
