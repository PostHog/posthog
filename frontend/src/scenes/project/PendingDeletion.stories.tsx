import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import preflightJson from '../../mocks/fixtures/_preflight.json'

// projectLogic reads the current project from the bootstrap app context, not an API call,
// so the pending-deletion state has to be set there.
const withPendingDeletionProject = (): (() => void) => {
    const appContext = window.POSTHOG_APP_CONTEXT
    const originalProject = appContext?.current_project
    if (appContext) {
        appContext.current_project = {
            ...MOCK_DEFAULT_PROJECT,
            is_pending_deletion: true,
            deletion_scheduled_at: dayjs().add(48, 'hours').toISOString(),
        }
    }
    return () => {
        if (appContext) {
            appContext.current_project = originalProject ?? null
        }
    }
}

const meta: Meta = {
    title: 'Scenes-Other/Project Pending Deletion',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.projectPendingDeletion(),
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const PendingDeletion: Story = { render: () => <App /> }

export const PendingDeletionWithDeleteNow: Story = {
    beforeEach: withPendingDeletionProject,
    render: () => <App />,
}

export const PendingDeletionNonAdmin: Story = {
    beforeEach: withPendingDeletionProject,
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/users/@me/': () => [
                        200,
                        {
                            email: 'test@posthog.com',
                            first_name: 'Test PostHog',
                            organization: { name: 'Test org', membership_level: 1, teams: [], projects: [] },
                            organizations: [],
                            team: null,
                        },
                    ],
                },
            },
        },
    },
    render: () => <App />,
}
