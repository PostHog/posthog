import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from './sidePanelStateLogic'

type StoryArgs = { panel: SidePanelTab }

const meta: Meta<StoryArgs> = {
    component: App,
    title: 'Scenes-App/SidePanels',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-10-10', // To stabilize relative dates
        pageUrl: urls.dashboards(),
        testOptions: {
            includeNavigationInSnapshot: true,
        },
    },
    render: ({ panel }) => {
        const { openSidePanel } = useActions(sidePanelStateLogic)
        useOnMountEffect(() => openSidePanel(panel))
        return <App />
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

type Story = StoryObj<StoryArgs>

export const SidePanelNotebooks: Story = {
    args: { panel: SidePanelTab.Notebooks },
}

export const SidePanelMax: Story = {
    args: { panel: SidePanelTab.Max },
}

export const SidePanelActivity: Story = {
    args: { panel: SidePanelTab.Activity },
    parameters: {
        pageUrl: urls.dashboard('1'),
        featureFlags: [FEATURE_FLAGS.CDP_ACTIVITY_LOG_NOTIFICATIONS, FEATURE_FLAGS.AUDIT_LOGS_ACCESS],
    },
}

export const SidePanelDiscussion: Story = {
    args: { panel: SidePanelTab.Discussion },
}

export const SidePanelAccessControl: Story = {
    args: { panel: SidePanelTab.AccessControl },
    parameters: {
        // AccessControl is only available on a scene that provides an access-control resource
        // context. On the dashboards list it wasn't, so the panel used to fall back to the Max
        // tab; point at a dashboard detail scene so the story renders the actual tab.
        pageUrl: urls.dashboard('1'),
    },
}

export const SidePanelInfo: Story = {
    args: { panel: SidePanelTab.Info },
    parameters: {
        // Info requires a scene that renders a ScenePanel; the dashboards list doesn't, so the
        // panel used to fall back to the Max tab. A dashboard detail scene provides it.
        pageUrl: urls.dashboard('1'),
    },
}

export const SidePanelExports: Story = {
    args: { panel: SidePanelTab.Exports },
}

export const SidePanelSupport: Story = {
    args: { panel: SidePanelTab.Support },
}
