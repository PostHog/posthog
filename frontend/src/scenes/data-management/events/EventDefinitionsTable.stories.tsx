import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const MOCK_EVENT_DEFINITIONS = {
    count: 5,
    next: null,
    previous: null,
    results: [
        {
            id: '1',
            name: '$pageview',
            description: 'When a user loads a page',
            tags: ['web', 'core'],
            last_seen_at: '2026-03-30T12:00:00Z',
            created_at: '2025-01-01T00:00:00Z',
            verified: true,
            verified_at: '2026-01-15T10:00:00Z',
            verified_by: 'user1',
            hidden: false,
        },
        {
            id: '2',
            name: '$autocapture',
            description: 'Automatically captured user interactions',
            tags: ['web'],
            last_seen_at: '2026-03-29T08:00:00Z',
            created_at: '2025-01-01T00:00:00Z',
            verified: true,
            verified_at: '2026-02-01T10:00:00Z',
            verified_by: 'user1',
            hidden: false,
        },
        {
            id: '3',
            name: 'sign_up',
            description: 'When a user signs up',
            tags: ['conversion'],
            last_seen_at: '2026-03-28T15:00:00Z',
            created_at: '2025-02-01T00:00:00Z',
            verified: false,
            hidden: false,
        },
        {
            id: '4',
            name: 'legacy_deprecated_event',
            description: 'An old event kept out of the UI by an admin',
            tags: ['legacy'],
            last_seen_at: '2026-03-25T10:00:00Z',
            created_at: '2025-03-01T00:00:00Z',
            verified: false,
            hidden: true,
        },
        {
            id: '5',
            name: '$identify',
            description: 'When a user is identified',
            tags: [],
            last_seen_at: '2026-03-31T09:00:00Z',
            created_at: '2025-01-01T00:00:00Z',
            verified: true,
            verified_at: '2026-03-01T10:00:00Z',
            verified_by: 'user2',
            hidden: false,
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Event Definitions',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-03-31',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/event_definitions/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const verified = params.get('verified')
                    let results = MOCK_EVENT_DEFINITIONS.results

                    if (verified === 'true') {
                        results = results.filter((e) => e.verified === true)
                    } else if (verified === 'false') {
                        results = results.filter((e) => !e.verified)
                    }

                    if (params.get('exclude_hidden') === 'true') {
                        results = results.filter((e) => !e.hidden)
                    }

                    return [200, { ...MOCK_EVENT_DEFINITIONS, results, count: results.length }]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    parameters: {
        pageUrl: urls.eventDefinitions(),
    },
}

export const FilteredVerifiedOnly: Story = {
    parameters: {
        pageUrl: urls.eventDefinitions() + '?verified=true',
    },
}

export const FilteredUnverifiedOnly: Story = {
    parameters: {
        pageUrl: urls.eventDefinitions() + '?verified=false',
    },
}

export const FilteredExcludeHidden: Story = {
    parameters: {
        pageUrl: urls.eventDefinitions() + '?excludeHidden=true',
    },
}
