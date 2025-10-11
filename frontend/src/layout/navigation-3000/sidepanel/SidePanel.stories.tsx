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

export const SidePanelSupportNoEmail: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Support} />
}

export const SidePanelSupportWithEmail: StoryFn = () => {
    const { openEmailForm } = useActions(supportLogic)

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

    useOnMountEffect(openEmailForm)

    return <BaseTemplate panel={SidePanelTab.Support} />
}

export const SidePanelSdkDoctor: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/detected-sdks/': () => [
                200,
                {
                    teamId: 997,
                    detections: [
                        {
                            type: 'web',
                            version: '1.275.1',
                            count: 45,
                            lastSeen: '2025-10-10T17:00:00Z',
                        },
                        {
                            type: 'web',
                            version: '1.271.0',
                            count: 30,
                            lastSeen: '2025-10-10T16:30:00Z',
                        },
                        {
                            type: 'web',
                            version: '1.200.0',
                            count: 15,
                            lastSeen: '2025-10-10T15:00:00Z',
                        },
                        {
                            type: 'react-native',
                            version: '4.9.1',
                            count: 20,
                            lastSeen: '2025-10-10T14:00:00Z',
                        },
                        {
                            type: 'react-native',
                            version: '4.8.1',
                            count: 12,
                            lastSeen: '2025-10-10T13:30:00Z',
                        },
                        {
                            type: 'react-native',
                            version: '4.6.0',
                            count: 8,
                            lastSeen: '2025-10-10T13:00:00Z',
                        },
                    ],
                    cached: false,
                    queriedAt: '2025-10-10T16:05:00Z',
                },
            ],
            '/api/github-sdk-versions/web/': {
                latestVersion: '1.275.1',
                versions: [
                    '1.275.1',
                    '1.275.0',
                    '1.274.3',
                    '1.274.2',
                    '1.274.1',
                    '1.274.0',
                    '1.273.0',
                    '1.272.0',
                    '1.271.0',
                    '1.270.0',
                    '1.269.0',
                    '1.268.0',
                    '1.267.0',
                ],
                releaseDates: {
                    '1.275.1': '2025-10-09T10:00:00Z',
                    '1.275.0': '2025-10-08T10:00:00Z',
                    '1.274.3': '2025-10-07T10:00:00Z',
                    '1.274.2': '2025-10-06T10:00:00Z',
                    '1.274.1': '2025-10-05T10:00:00Z',
                    '1.274.0': '2025-10-04T10:00:00Z',
                    '1.273.0': '2025-10-03T10:00:00Z',
                    '1.272.0': '2025-10-02T10:00:00Z',
                    '1.271.0': '2025-10-01T10:00:00Z',
                    '1.270.0': '2025-09-28T10:00:00Z',
                    '1.269.0': '2025-09-25T10:00:00Z',
                    '1.268.0': '2025-09-20T10:00:00Z',
                    '1.267.0': '2025-09-15T10:00:00Z',
                },
                cached: true,
            },
            '/api/github-sdk-versions/react-native/': {
                latestVersion: '4.9.1',
                versions: ['4.9.1', '4.9.0', '4.8.1', '4.8.0', '4.7.0', '4.6.0', '4.5.0', '4.4.3'],
                releaseDates: {
                    '4.9.1': '2025-10-08T10:00:00Z',
                    '4.9.0': '2025-09-28T10:00:00Z',
                    '4.8.1': '2025-09-15T10:00:00Z',
                    '4.8.0': '2025-09-01T10:00:00Z',
                    '4.7.0': '2025-08-15T10:00:00Z',
                    '4.6.0': '2025-08-01T10:00:00Z',
                    '4.5.0': '2025-07-15T10:00:00Z',
                    '4.4.3': '2025-06-20T10:00:00Z',
                },
                cached: true,
            },
        },
    })

    return <BaseTemplate panel={SidePanelTab.SdkDoctor} />
}

SidePanelSdkDoctor.parameters = {
    featureFlags: [FEATURE_FLAGS.SDK_DOCTOR_BETA],
}
