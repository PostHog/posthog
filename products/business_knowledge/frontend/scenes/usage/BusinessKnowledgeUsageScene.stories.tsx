import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { KnowledgeUsageApi } from '../../generated/api.schemas'

const DAILY_COUNTS = [2, 0, 3, 5, 4, 1, 0, 6, 7, 3, 4, 2, 0, 1, 5, 8, 6, 4, 3, 0, 2, 7, 9, 5, 4, 6, 3, 1, 8, 10]

const usage: KnowledgeUsageApi = {
    days: 30,
    cited_run_count: 119,
    learned_cited_run_count: 34,
    source_count: 12,
    cited_source_count: 7,
    daily: DAILY_COUNTS.map((cited_run_count, index) => ({
        date: `2022-12-${String(index + 1).padStart(2, '0')}`,
        cited_run_count,
    })),
    top_sources: [
        {
            source_id: 'source-1',
            name: 'Refunds and cancellations',
            is_generated: false,
            cited_run_count: 41,
            last_cited_at: '2023-01-28T08:15:00Z',
        },
        {
            source_id: 'source-2',
            name: 'How to change the billing email on an annual plan',
            is_generated: true,
            cited_run_count: 22,
            last_cited_at: '2023-01-27T16:40:00Z',
        },
        {
            source_id: 'source-3',
            name: 'Help center',
            is_generated: false,
            cited_run_count: 17,
            last_cited_at: '2023-01-25T11:05:00Z',
        },
    ],
}

const USAGE_URL = '/api/projects/:team_id/business_knowledge/sources/usage/'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Business knowledge/Usage',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28T10:00:00Z',
        featureFlags: [FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE],
        pageUrl: urls.businessKnowledgeUsage(),
        // A scene used by one product: render it in CI, but keep no visual baseline.
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [mswDecorator({ get: { [USAGE_URL]: usage } })],
}
export default meta

type Story = StoryObj<{}>

export const WithCitations: Story = {}

export const NoCitations: Story = {
    decorators: [
        mswDecorator({
            get: {
                [USAGE_URL]: {
                    ...usage,
                    cited_run_count: 0,
                    learned_cited_run_count: 0,
                    cited_source_count: 0,
                    top_sources: [],
                },
            },
        }),
    ],
}

export const LoadFailed: Story = {
    decorators: [mswDecorator({ get: { [USAGE_URL]: () => [500, { detail: 'Server error' }] } })],
}
