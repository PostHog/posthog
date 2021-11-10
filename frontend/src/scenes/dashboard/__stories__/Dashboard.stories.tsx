import React from 'react'
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'
import { worker } from '../../../mocks/browser'
import { rest } from 'msw'
import { Dashboard } from '../Dashboard'
import originalDashboardState from './dashboard.json'

const dashboardItems = [
    require('./items/trends-pageviews.json'),
    require('./items/retention.json'),
    require('./items/funnel-time-to-convert.json'),
]

const dashboardState = {
    ...originalDashboardState,
    scenes: {
        ...originalDashboardState.scenes,
        dashboard: {
            ...originalDashboardState.scenes.dashboard,
            dashboardLogic: {
                ...originalDashboardState.scenes.dashboard.dashboardLogic,
                1: {
                    ...originalDashboardState.scenes.dashboard.dashboardLogic['1'],
                    allItems: {
                        ...originalDashboardState.scenes.dashboard.dashboardLogic['1'].allItems,
                        items: dashboardItems.map((item) => ({ ...item, layouts: null })),
                    },
                },
            },
        },
    },
}
//;(dashboardState.scenes.dashboard.dashboardLogic['1'].allItems as any) = [pageviews])

export default {
    title: 'PostHog/Scenes/Dashboard',
    decorators: [
        (Story) => {
            worker.use(
                rest.get('/api/organizations/@current/', (_, res, ctx) => {
                    return res(ctx.json(dashboardState.scenes.organizationLogic.currentOrganization))
                }),
                rest.get('/api/projects/@current/', (_, res, ctx) => {
                    return res(ctx.json(dashboardState.scenes.teamLogic.currentTeam))
                }),
                rest.get('/api/users/@me/', (_, res, ctx) => {
                    return res(ctx.json(dashboardState.scenes.userLogic.user))
                }),
                rest.get('/api/instance_status/', (_, res, ctx) => {
                    return res(ctx.json(dashboardState.scenes.instance.SystemStatus.systemStatusLogic.systemStatus))
                }),
                rest.get('/api/projects/1/annotations/', (_, res, ctx) => {
                    return res(ctx.json(dashboardState.models.annotationsModel.globalAnnotations))
                }),
                rest.get('/api/projects/1/actions/', (_, res, ctx) => {
                    return res(ctx.json(dashboardState.models.actionsModel.actions))
                }),
                rest.get('/api/projects/1/dashboards/1/', (_, res, ctx) => {
                    return res(ctx.json(dashboardState.scenes.dashboard.dashboardLogic['1'].allItems))
                }),
                rest.get('/api/projects/1/dashboards/', (_, res, ctx) => {
                    return res(ctx.json(Object.values(dashboardState.models.dashboardsModel.rawDashboards)))
                })
            )
            return <Story />
        },
    ],
} as Meta

export const AllPossibleInsightTypes = keaStory(function DashboardInner() {
    return <Dashboard id={dashboardState.scenes.dashboard.dashboardLogic['1'].allItems.id.toString()} />
}, dashboardState)
