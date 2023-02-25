import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { useAvailableFeatures } from '~/mocks/features'
import { DashboardMode } from '~/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardTemplatesLogic } from './dashboards/templates/dashboardTemplatesLogic'

export default {
    title: 'Scenes-App/Dashboards',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboards/': require('./__mocks__/dashboards.json'),
                '/api/projects/:team_id/dashboards/1/': require('./__mocks__/dashboard1.json'),
                '/api/projects/:team_id/dashboards/1/collaborators/': [],
                '/api/projects/:team_id/dashboard_templates/': [],
                '/api/projects/:team_id/dashboard_templates/json_schema/': require('./__mocks__/dashboard_template_schema.json'),
                '/api/projects/:team_id/dashboards/:dash_id/sharing/': {
                    created_at: '2023-02-25T13:28:20.454940Z',
                    enabled: false,
                    access_token: 'a-secret-token',
                },
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
        mockDate: '2023-02-01',
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
        dashboardTemplatesLogic.mount()
        dashboardTemplatesLogic.actions.setTemplates([
            {
                id: '1',
                template_name: 'Simple Dashboard Template',
                dashboard_description: 'A simple dashboard template',
                dashboard_filters: {},
                tiles: [],
                variables: [],
                tags: [],
                image_url:
                    'https://posthog.com/static/5e5cf65347bfb25f1dfc9792b18e87cb/6b063/posthog-bye-kubernetes.png',
            },
            {
                id: '2',
                template_name: 'Very long named dashboard template',
                dashboard_description:
                    'Very long dashboard description, it keeps going and going and going and going and going and going and going and going and going and going and going and going and going',
                dashboard_filters: {},
                tiles: [],
                variables: [],
                tags: [],
                image_url:
                    'https://posthog.com/static/2ba70f2c4650b4b77e4d8cd10324a093/b5380/posthog-ceo-diary-blog.png',
            },
            {
                id: '3',
                template_name: 'Same again template',
                dashboard_description:
                    'Very long dashboard description, it keeps going and going and going and going and going and going and going and going and going and going and going and going and going',
                dashboard_filters: {},
                tiles: [],
                variables: [],
                tags: [],
                image_url:
                    'https://posthog.com/static/2ba70f2c4650b4b77e4d8cd10324a093/b5380/posthog-ceo-diary-blog.png',
            },
            {
                id: '4',
                template_name: 'Same again template',
                dashboard_description:
                    'Very long dashboard description, it keeps going and going and going and going and going and going and going and going and going and going and going and going and going',
                dashboard_filters: {},
                tiles: [],
                variables: [],
                tags: [],
                image_url:
                    'https://posthog.com/static/2ba70f2c4650b4b77e4d8cd10324a093/b5380/posthog-ceo-diary-blog.png',
            },
            {
                id: '4',
                template_name: 'Broken image',
                dashboard_description:
                    'Very long dashboard description, it keeps going and going and going and going and going and going and going and going and going and going and going and going and going',
                dashboard_filters: {},
                tiles: [],
                variables: [],
                tags: [],
                image_url: 'broken-image.png',
            },
            {
                id: '5',
                template_name: 'Broken image 2',
                dashboard_description:
                    'Very long dashboard description, it keeps going and going and going and going and going and going and going and going and going and going and going and going and going',
                dashboard_filters: {},
                tiles: [],
                variables: [],
                tags: [],
                image_url: 'broken-image.png',
            },
        ])
    }, [])
    return <App />
}

export const NewSelectVariables = (): JSX.Element => {
    useAvailableFeatures([])
    useEffect(() => {
        router.actions.push(urls.dashboards())
        newDashboardLogic.mount()
        newDashboardLogic.actions.showNewDashboardModal()
        newDashboardLogic.actions.setActiveDashboardTemplate({
            id: '1',
            template_name: 'Dashboard name',
            dashboard_description: 'The dashboard description',
            dashboard_filters: {},
            tiles: [],
            variables: [
                {
                    id: 'SIGN_UP',
                    name: 'Sign up page viewed',
                    type: 'event',
                    default: {
                        id: '$pageview',
                        math: 'dau',
                        type: 'events',
                    },
                    required: true,
                    description: 'Add the current_url filter that matches your sign up page',
                },
                {
                    id: 'ACTIVATED',
                    name: 'Very very long event name very very long. Very very long event name very very long',
                    type: 'event',
                    default: {
                        id: '$pageview',
                        math: 'dau',
                        type: 'events',
                    },
                    required: true,
                    description:
                        'Very long description. Select the event which best represents when a user is activated. Select the event which best represents when a user is activated',
                },
                {
                    id: 'ACTIVATED',
                    name: 'Activated event',
                    type: 'event',
                    default: {
                        id: '$pageview',
                        math: 'dau',
                        type: 'events',
                    },
                    required: false,
                    description: 'Select the event which best represents when a user is activated',
                },
            ],
            tags: [],
            image_url: 'https://posthog.com/static/5e5cf65347bfb25f1dfc9792b18e87cb/6b063/posthog-bye-kubernetes.png',
        })
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
