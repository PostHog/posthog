import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature, DashboardMode } from '~/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

export default {
    title: 'Scenes-App/Dashboards',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboards/': require('./__mocks__/dashboards.json'),
                '/api/projects/:team_id/dashboards/1/': require('./__mocks__/dashboard1.json'),
                '/api/projects/:team_id/dashboards/1/collaborators/': [],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
    },
} as Meta

export const List = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.dashboards())
    }, [])
    return <App />
}

export const New = (): JSX.Element => {
    useAvailableFeatures([])
    useEffect(() => {
        router.actions.push(urls.dashboards())
        newDashboardLogic.mount()
        newDashboardLogic.actions.showNewDashboardModal()
    }, [])
    return <App />
}

export const NewPremium = (): JSX.Element => {
    useAvailableFeatures([AvailableFeature.DASHBOARD_PERMISSIONING])
    useEffect(() => {
        router.actions.push(urls.dashboards())
        newDashboardLogic.mount()
        newDashboardLogic.actions.showNewDashboardModal()
    }, [])
    return <App />
}

export const Show = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.dashboard(1))
    }, [])
    return <App />
}

export const Edit = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.dashboard(1))
        dashboardLogic({ id: 1 }).mount()
        dashboardLogic({ id: 1 }).actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.Browser)
    }, [])
    return <App />
}
