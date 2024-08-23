import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'

import { sidePanelStateLogic, SidePanelTab } from './sidePanelStateLogic'

const meta: Meta = {
    title: 'Scenes-App/SidePanels',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
        testOptions: {
            includeNavigationInSnapshot: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboard_templates/': {},
                '/api/projects/:id/integrations': { results: [] },
            },
            post: {
                '/api/projects/:team_id/query': {},
            },
        }),
    ],
}
export default meta

const BaseTemplate = (props: { panel: SidePanelTab }): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    useEffect(() => {
        router.actions.push(urls.dashboards())
        openSidePanel(props.panel)
    }, [])

    return <App />
}

export const SidePanelDocs: StoryFn = () => {
    return <BaseTemplate panel="docs" />
}

export const SidePanelSettings: StoryFn = () => {
    return <BaseTemplate panel="settings" />
}

export const SidePanelActivation: StoryFn = () => {
    return <BaseTemplate panel="activation" />
}

export const SidePanelNotebooks: StoryFn = () => {
    return <BaseTemplate panel="notebook" />
}

export const SidePanelSupportNoEmail: StoryFn = () => {
    return <BaseTemplate panel="support" />
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
    return <BaseTemplate panel="support" />
}
