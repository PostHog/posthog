import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { ActionType } from '~/types'

const MOCK_ACTION: ActionType = {
    created_at: '',
    id: 1,
    name: 'My action',
    created_by: MOCK_DEFAULT_BASIC_USER,
    steps: [
        {
            event: '$pageview',
            tag_name: 'button',
            selector: '.signup-button',
            url: 'https://posthog.com/signup',
            href: 'https://posthog.com/signup',
            text: 'Sign up',
            url_matching: 'contains',
        },
    ],
}

const meta: Meta = {
    title: 'Scenes-App/Data Management/Actions',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/actions/': toPaginatedResponse([MOCK_ACTION]),
                '/api/projects/:team_id/actions/1/': MOCK_ACTION,
            },
        }),
    ],
}
export default meta
export const ActionsList: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.actions())
    }, [])
    return <App />
}

export const Action: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.action(MOCK_ACTION.id))
    }, [])
    return <App />
}
Action.parameters = {
    testOptions: {
        waitForSelector: '.card-secondary',
    },
}
