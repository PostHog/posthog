import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { RequestStatusEnumApi } from '~/generated/core/api.schemas'
import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

const REQUEST = {
    id: '0198eeee-0000-7000-8000-000000000001',
    status: RequestStatusEnumApi.Pending,
    query: "SELECT uuid\nFROM events\nWHERE event = 'example_event'\n    AND timestamp < '2026-01-01'",
    variables: {},
    submission_id: '0198ffff-0000-4000-8000-000000000001',
    count: 1250,
    created_by_id: 1,
    created_by_staff: false,
    created_at: '2026-10-20T10:00:00Z',
    updated_at: '2026-10-20T10:00:00Z',
    approved_at: null,
    stats_calculated_at: '2026-10-20T10:00:00Z',
}

const REQUESTS = [
    REQUEST,
    {
        ...REQUEST,
        id: '0198eeee-0000-7000-8000-000000000002',
        status: RequestStatusEnumApi.Queued,
        count: 48,
        created_at: '2026-10-10T10:00:00Z',
        approved_at: '2026-10-11T09:00:00Z',
    },
    {
        ...REQUEST,
        id: '0198eeee-0000-7000-8000-000000000003',
        status: RequestStatusEnumApi.Completed,
        count: 2,
        created_at: '2026-09-01T10:00:00Z',
        approved_at: '2026-09-02T09:00:00Z',
    },
]

interface StoryProps {
    url: string
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-App/Settings/Data deletion',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.SELF_SERVICE_DATA_DELETION],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/data_deletion_requests/': {
                    count: REQUESTS.length,
                    next: null,
                    previous: null,
                    results: REQUESTS,
                },
            },
            post: {
                '/api/projects/:id/data_deletion_requests/preview/': { count: 1250 },
            },
        }),
    ],
    beforeEach: () => {
        const appContext = window.POSTHOG_APP_CONTEXT
        if (!appContext) {
            return
        }
        const originalAccess = appContext.resource_access_control
        appContext.resource_access_control = {
            ...originalAccess,
            [AccessControlResourceType.DataDeletion]: AccessControlLevel.Editor,
        }
        return () => {
            appContext.resource_access_control = originalAccess
        }
    },
    render: ({ url }) => {
        router.actions.push(url)
        return <App />
    },
}
export default meta

export const RequestList: Story = { args: { url: urls.settings('environment-data-deletion') } }
export const NewRequest: Story = { args: { url: urls.dataDeletionRequestNew() } }
