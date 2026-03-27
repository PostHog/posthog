import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { INCIDENT_IO_STATUS_PAGE_BASE } from '~/layout/navigation-3000/incident/incidentStatus'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import * as incidentIoStatusPageCritical from '~/mocks/fixtures/_incident_io_status_page_critical.json'
import * as incidentIoStatusPageWarning from '~/mocks/fixtures/_incident_io_status_page_warning.json'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import { SidePanelTab } from '~/types'

import { sidePanelDocsLogic } from './panels/sidePanelDocsLogic'
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
                '/api/environments/:team_id/query': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<StoryArgs>

export const SidePanelDocs: Story = {
    args: { panel: SidePanelTab.Docs },
    render: ({ panel }) => {
        const { openSidePanel } = useActions(sidePanelStateLogic)
        const { setIframeReady } = useActions(sidePanelDocsLogic({ iframeRef: { current: null } }))

        // Directly set iframeReady to skip waiting for external iframe to load
        useOnMountEffect(() => {
            openSidePanel(panel)
            setIframeReady(true)
        })

        return <App />
    },
    parameters: {
        testOptions: {
            // Skip iframe wait since the external docs iframe fails to load in CI
            skipIframeWait: true,
        },
    },
}

export const SidePanelSettings: Story = {
    args: { panel: SidePanelTab.Settings },
}

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

export const SidePanelSupportNoEmail: Story = {
    args: { panel: SidePanelTab.Support },
}

export const SidePanelSupportWithEmail: Story = {
    args: { panel: SidePanelTab.Support },
    render: ({ panel }) => {
        const { openSidePanel } = useActions(sidePanelStateLogic)
        const { openEmailForm, closeEmailForm } = useActions(supportLogic)

        useStorybookMocks({
            get: {
                // TODO: setting available featues should be a decorator to make this easy
                '/api/users/@me': () => [
                    200,
                    {
                        email: 'test@posthog.com',
                        first_name: 'Test Hedgehog',
                        organization: {
                            ...organizationCurrent,
                            available_product_features: [
                                {
                                    key: 'email_support',
                                    name: 'Email support',
                                },
                            ],
                        },
                    },
                ],
            },
        })

        useOnMountEffect(() => {
            openSidePanel(panel)
            openEmailForm()
            return () => closeEmailForm()
        })

        return <App />
    },
}

export const SidePanelStatusWarning: Story = {
    render: () => {
        const { closeSidePanel } = useActions(sidePanelStateLogic)
        useOnMountEffect(() => closeSidePanel())
        const summary = Object.assign({}, incidentIoStatusPageWarning)

        useStorybookMocks({
            get: {
                [`${INCIDENT_IO_STATUS_PAGE_BASE}/api/v1/summary`]: summary,
            },
        })

        return <App />
    },
}

export const SidePanelStatusCritical: Story = {
    render: () => {
        const { closeSidePanel } = useActions(sidePanelStateLogic)
        useOnMountEffect(() => closeSidePanel())

        const summary = Object.assign({}, incidentIoStatusPageCritical)

        useStorybookMocks({
            get: {
                [`${INCIDENT_IO_STATUS_PAGE_BASE}/api/v1/summary`]: summary,
            },
        })

        return <App />
    },
}
