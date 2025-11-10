import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from './sidePanelStateLogic'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/SidePanels',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-10-10', // To stabilize relative dates
        pageUrl: urls.dashboards(),
        featureFlags: [FEATURE_FLAGS.SDK_DOCTOR_BETA],
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
    return <BaseTemplate panel={SidePanelTab.Docs} />
}
SidePanelDocs.parameters = {
    testOptions: {
        // Wait for iframe to load - it's hidden until ready
        waitForSelector: 'iframe[title="Docs"]:not(.hidden)',
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
