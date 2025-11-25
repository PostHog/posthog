import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const savedList = {
    count: 2,
    results: [
        {
            id: 1,
            short_id: 'hm_abc123',
            name: 'Homepage heatmap',
            url: 'https://posthog.com',
            data_url: 'https://posthog.com',
            target_widths: [768, 1024, 1440],
            type: 'screenshot',
            status: 'completed',
            has_content: true,
            snapshots: [
                { width: 768, has_content: true },
                { width: 1024, has_content: true },
            ],
            deleted: false,
            created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            exception: null,
        },
        {
            id: 2,
            short_id: 'hm_def456',
            name: 'Pricing page',
            url: 'https://posthog.com/pricing',
            data_url: 'https://posthog.com/pricing',
            target_widths: [1024, 1440],
            type: 'iframe',
            status: 'completed',
            has_content: false,
            snapshots: [],
            deleted: false,
            created_by: { id: 2, uuid: 'user-2', distinct_id: 'd2', first_name: 'Bob', email: 'bob@ph.com' },
            created_at: '2024-01-02T00:00:00Z',
            updated_at: '2024-01-02T00:00:00Z',
            exception: null,
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Heatmaps Saved',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.heatmaps(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/saved/': savedList,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const List: Story = {}
