import React, { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { newDashboardForm } from 'scenes/dashboard/newDashboardForm'
import { useFeatures } from '~/mocks/features'
import { AvailableFeature, DashboardMode } from '~/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

export default {
    title: 'Scenes-App/Dashboard',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:projectId/dashboards/': require('./__mocks__/dashboards.json'),
                '/api/projects/:projectId/dashboards/1/': require('./__mocks__/dashboard1.json'),
                '/api/projects/:projectId/dashboards/1/collaborators/': [],
            },
        }),
    ],
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export const List = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.dashboards())
    }, [])
    return <App />
}

export const New = (): JSX.Element => {
    useFeatures([])
    useEffect(() => {
        router.actions.push(urls.dashboards())
        newDashboardForm.mount()
        newDashboardForm.actions.showNewDashboardModal()
    }, [])
    return <App />
}

export const NewPremium = (): JSX.Element => {
    useFeatures([AvailableFeature.DASHBOARD_PERMISSIONING])
    useEffect(() => {
        router.actions.push(urls.dashboards())
        newDashboardForm.mount()
        newDashboardForm.actions.showNewDashboardModal()
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
