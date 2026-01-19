import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import * as incidentIoStatusPageCritical from '~/mocks/fixtures/_incident_io_status_page_critical.json'
import * as incidentIoStatusPageWarning from '~/mocks/fixtures/_incident_io_status_page_warning.json'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import { SidePanelTab } from '~/types'

import { sidePanelDocsLogic } from './panels/sidePanelDocsLogic'
import { INCIDENT_IO_STATUS_PAGE_BASE } from './panels/sidePanelStatusIncidentIoLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/SidePanels',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-10-10', // To stabilize relative dates
        pageUrl: urls.dashboards(),
        featureFlags: [FEATURE_FLAGS.INCIDENT_IO_STATUS_PAGE],
        testOptions: {
            includeNavigationInSnapshot: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboard_templates/': {},
                '/api/projects/:id/integrations': { results: [] },
                '/api/organizations/@current/pipeline_destinations/': { results: [] },
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

const BaseTemplate = (props: { panel: SidePanelTab }): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    useOnMountEffect(() => openSidePanel(props.panel))

    return <App />
}

export const SidePanelDocs: StoryFn = () => {
    const { setIframeReady } = useActions(sidePanelDocsLogic({ iframeRef: { current: null } }))

    // Directly set iframeReady to skip waiting for external iframe to load
    useOnMountEffect(() => {
        setIframeReady(true)
    })

    return <BaseTemplate panel={SidePanelTab.Docs} />
}
SidePanelDocs.parameters = {
    testOptions: {
        // Skip iframe wait since the external docs iframe fails to load in CI
        skipIframeWait: true,
    },
}

export const SidePanelSettings: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Settings} />
}

export const SidePanelActivation: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Activation} />
}

export const SidePanelNotebooks: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Notebooks} />
}

export const SidePanelMax: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Max} />
}

export const SidePanelSdkDoctor: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.SdkDoctor} />
}

export const SidePanelActivity: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Activity} />
}
SidePanelActivity.parameters = {
    pageUrl: urls.dashboard('1'),
    featureFlags: [
        FEATURE_FLAGS.INCIDENT_IO_STATUS_PAGE,
        FEATURE_FLAGS.CDP_ACTIVITY_LOG_NOTIFICATIONS,
        FEATURE_FLAGS.AUDIT_LOGS_ACCESS,
    ],
}

export const SidePanelSupportNoEmail: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Support} />
}

export const SidePanelSupportWithEmail: StoryFn = () => {
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
        openEmailForm()
        return () => closeEmailForm()
    })

    return <BaseTemplate panel={SidePanelTab.Support} />
}

export const SidePanelStatusWarning: StoryFn = () => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    useOnMountEffect(() => closeSidePanel())
    const summary = Object.assign({}, incidentIoStatusPageWarning)

    useStorybookMocks({
        get: {
            [`${INCIDENT_IO_STATUS_PAGE_BASE}/api/v1/summary`]: summary,
        },
    })

    return <App />
}

export const SidePanelStatusCritical: StoryFn = () => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    useOnMountEffect(() => closeSidePanel())

    const summary = Object.assign({}, incidentIoStatusPageCritical)

    useStorybookMocks({
        get: {
            [`${INCIDENT_IO_STATUS_PAGE_BASE}/api/v1/summary`]: summary,
        },
    })

    return <App />
}
