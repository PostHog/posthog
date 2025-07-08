import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, setFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from './sidePanelStateLogic'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/SidePanels',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
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
    useEffect(() => {
        openSidePanel(props.panel)
    }, [])

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

export const SidePanelFeaturePreviews: StoryFn = () => {
    useStorybookMocks({
        get: {
            'https://us.i.posthog.com/api/early_access_features/': {
                earlyAccessFeatures: [
                    {
                        name: 'Feature 1',
                        description:
                            'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Curabitur tristique arcu et orci lobortis condimentum. Donec placerat orci in ipsum vestibulum, rutrum commodo leo tincidunt. Nullam vitae varius neque.',
                        stage: 'beta',
                        documentationUrl: 'https://docs.example.com',
                        flagKey: 'feature-1',
                    },
                    {
                        name: 'Feature 2',
                        description:
                            'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Curabitur tristique arcu et orci lobortis condimentum. Donec placerat orci in ipsum vestibulum, rutrum commodo leo tincidunt. Nullam vitae varius neque.',
                        stage: 'beta',
                        documentationUrl: 'https://docs.example.com',
                        flagKey: 'feature-2',
                    },
                    {
                        name: 'Feature 3',
                        description:
                            'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Curabitur tristique arcu et orci lobortis condimentum. Donec placerat orci in ipsum vestibulum, rutrum commodo leo tincidunt. Nullam vitae varius neque.',
                        stage: 'beta',
                        documentationUrl: 'https://docs.example.com',
                        flagKey: 'feature-3',
                    },
                    {
                        name: 'Feature 4',
                        description:
                            'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Curabitur tristique arcu et orci lobortis condimentum. Donec placerat orci in ipsum vestibulum, rutrum commodo leo tincidunt. Nullam vitae varius neque.',
                        stage: 'beta',
                        documentationUrl: 'https://docs.example.com',
                        flagKey: 'feature-4',
                    },
                    {
                        name: 'Feature 5',
                        description:
                            'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Curabitur tristique arcu et orci lobortis condimentum. Donec placerat orci in ipsum vestibulum, rutrum commodo leo tincidunt. Nullam vitae varius neque.',
                        stage: 'beta',
                        documentationUrl: 'https://docs.example.com',
                        flagKey: 'feature-5',
                    },
                    {
                        name: 'Not enabled',
                        description:
                            'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Curabitur tristique arcu et orci lobortis condimentum. Donec placerat orci in ipsum vestibulum, rutrum commodo leo tincidunt. Nullam vitae varius neque.',
                        stage: 'beta',
                        documentationUrl: 'https://docs.example.com',
                        flagKey: 'not-enabled',
                    },
                ],
            },
        },
    })
    setFeatureFlags(['feature-1', 'feature-2', 'feature-3', 'feature-4', 'feature-5'])
    return <BaseTemplate panel={SidePanelTab.FeaturePreviews} />
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

    useEffect(() => {
        openEmailForm()
    }, [])

    return <BaseTemplate panel={SidePanelTab.Support} />
}
