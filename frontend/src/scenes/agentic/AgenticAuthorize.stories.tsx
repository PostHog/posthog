import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const pushAuthorize = (): void => {
    router.actions.push(`${urls.agenticAuthorize()}?state=test-state`)
}

const meta: Meta = {
    title: 'Scenes-App/Agentic/Authorize',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        testOptions: {
            waitForSelector: '.max-w-2xl',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/agentic/authorize/pending/': {
                    partner_name: 'Acme',
                    scopes: ['feature_flag:read'],
                },
                '/api/organizations/:organization_id/projects/': {
                    results: [{ id: 1, name: 'Default Project', organization: MOCK_DEFAULT_ORGANIZATION.id }],
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => {
        useDelayedOnMountEffect(pushAuthorize)
        return <App />
    },
}

// The project list failed. The picker offers a way back instead of staying empty forever, which
// is what blocked the partner connect flow with no way out.
export const ProjectsLoadFailed: Story = {
    decorators: [mswDecorator({ get: { '/api/organizations/:organization_id/projects/': () => [500] } })],
    render: () => {
        useDelayedOnMountEffect(pushAuthorize)
        return <App />
    },
}
