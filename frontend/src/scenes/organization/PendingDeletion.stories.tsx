import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import preflightJson from '../../mocks/fixtures/_preflight.json'

const meta: Meta = {
    title: 'Scenes-Other/Organization Pending Deletion',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.organizationPendingDeletion(),
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
                '/api/organizations/@current/': () => [
                    200,
                    {
                        id: '018e1b6b-0000-0000-0000-000000000002',
                        name: 'Test org',
                        membership_level: 15,
                        is_pending_deletion: true,
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

export const PendingDeletion: Story = { render: () => <App /> }
