import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { panelLayoutLogic } from '../panelLayoutLogic'

const meta: Meta<typeof App> = {
    component: App,
    title: 'Scenes-App/Navigation',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-10-10',
        pageUrl: urls.dashboards(),
        testOptions: {
            includeNavigationInSnapshot: true,
            viewportWidths: ['narrow', 'medium', 'wide'],
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboard_templates/': {},
                '/api/projects/:id/integrations': { results: [] },
                '/api/organizations/:organization_id/pipeline_destinations/': { results: [] },
                '/api/projects/:id/pipeline_destination_configs/': { results: [] },
                '/api/projects/:id/batch_exports/': { results: [] },
                '/api/projects/:id/surveys/': { results: [] },
                '/api/projects/:id/surveys/responses_count/': { results: [] },
                '/api/environments/:team_id/exports/': { results: [] },
                '/api/environments/:team_id/events': { results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof App>

export const Expanded: Story = {
    render: () => {
        const { toggleLayoutNavCollapsed } = useActions(panelLayoutLogic)
        useOnMountEffect(() => toggleLayoutNavCollapsed(false))
        return <App />
    },
}

export const Collapsed: Story = {
    render: () => {
        const { toggleLayoutNavCollapsed } = useActions(panelLayoutLogic)
        useOnMountEffect(() => toggleLayoutNavCollapsed(true))
        return <App />
    },
}
