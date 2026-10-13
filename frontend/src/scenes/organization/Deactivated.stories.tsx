import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import preflightJson from '../../mocks/fixtures/_preflight.json'

const meta: Meta = {
    title: 'Scenes-Other/Organization Deactivated',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.organizationDeactivated(),
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/api/users/@me/': () => [
                    200,
                    {
                        email: 'test@posthog.com',
                        first_name: 'Test PostHog',
                        organization: { name: 'Test org', teams: [], projects: [] },
                        organizations: [],
                        team: null,
                    },
                ],
                // The reason below is the only place a revoked organization learns why.
                '/api/organizations/@current/': () => [
                    200,
                    {
                        id: '018e1b6b-0000-0000-0000-000000000001',
                        name: 'Test org',
                        membership_level: 15,
                        is_active: false,
                        is_not_active_reason: 'Access revoked due to unpaid balance.',
                        teams: [],
                        projects: [],
                    },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Deactivated: Story = { render: () => <App /> }
