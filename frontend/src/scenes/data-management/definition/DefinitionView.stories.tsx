import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const MOCK_EVENT_DEFINITION = {
    id: '1',
    name: 'order_placed',
    description: 'When a customer completes a checkout',
    tags: ['conversion', 'revenue'],
    last_seen_at: '2026-04-29T18:00:00Z',
    last_updated_at: '2026-04-29T18:00:00Z',
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2026-04-15T10:00:00Z',
    verified: true,
    verified_at: '2026-02-01T10:00:00Z',
    verified_by: { id: 1, first_name: 'Demo', email: 'demo@posthog.com' },
    hidden: false,
    primary_property: 'order_id',
    media_preview_urls: [],
    is_action: false,
    is_calculating: false,
    last_calculated_at: null,
    enforcement_mode: 'allow',
    post_to_slack: false,
    default_columns: [],
    owner: null,
    created_by: { id: 1, first_name: 'Demo', email: 'demo@posthog.com' },
}

const MOCK_METRICS = { query_usage_30_day: 12345 }

const MOCK_PROPERTY_DEFINITION = {
    id: '2',
    name: 'plan',
    description: 'Billing plan of the account that sent the event',
    tags: ['billing'],
    is_numerical: false,
    property_type: 'String',
    verified: true,
    hidden: false,
    updated_at: '2026-04-15T10:00:00Z',
    updated_by: null,
}

const mockUser = (id: number, first_name: string, email: string): Record<string, unknown> => ({
    id,
    uuid: `0000000${id}-0000-0000-0000-000000000000`,
    distinct_id: `user-${id}`,
    first_name,
    last_name: '',
    email,
    is_email_verified: true,
    hedgehog_config: null,
    role_at_organization: null,
})

const MOCK_PROPERTY_USAGE = {
    query_usage_30_day: 1236,
    last_queried_at: '2026-04-29T18:00:00Z',
    daily: Array.from({ length: 30 }, (_, index) => ({
        date: `2026-04-${String(index + 1).padStart(2, '0')}`,
        count: index % 7 >= 5 ? 6 : 30 + ((index * 13) % 25),
    })),
    top_users: [
        { user: mockUser(1, 'Ada', 'ada@example.com'), count: 640, last_queried_at: '2026-04-29T18:00:00Z' },
        { user: mockUser(2, 'Grace', 'grace@example.com'), count: 311, last_queried_at: '2026-04-28T14:00:00Z' },
        { user: mockUser(3, 'Linus', 'linus@example.com'), count: 73, last_queried_at: '2026-04-12T08:00:00Z' },
    ],
    distinct_users: 4,
    automated_query_usage_30_day: 196,
}

const MOCK_PROPERTY_INSIGHTS = {
    count: 2,
    next: null,
    previous: null,
    results: [
        {
            id: 1,
            short_id: 'abc123',
            name: 'Signups by plan',
            description: '',
            query: null,
            created_by: mockUser(1, 'Ada', 'ada@example.com'),
            created_at: '2026-03-01T10:00:00Z',
            last_modified_at: '2026-04-20T10:00:00Z',
        },
        {
            id: 2,
            short_id: 'def456',
            name: 'Revenue by plan',
            description: '',
            query: null,
            created_by: mockUser(2, 'Grace', 'grace@example.com'),
            created_at: '2026-02-01T10:00:00Z',
            last_modified_at: '2026-04-25T10:00:00Z',
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Definition View',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-04-30',
        pageUrl: urls.eventDefinition(MOCK_EVENT_DEFINITION.id),
        // The full DefinitionView mounts EventDefinitionProperties / DefinitionInsights / a
        // matching-events table — those keep their loaders spinning because we don't mock every
        // downstream endpoint. The metadata row (Status + Primary property) is what this story
        // exists to capture, so don't block on loaders that are intentionally never going to settle.
        testOptions: {
            waitForLoadersToDisappear: false,
            viewportWidths: ['narrow', 'medium', 'wide', 'superwide'],
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/event_definitions/:id/': MOCK_EVENT_DEFINITION,
                '/api/projects/:project_id/event_definitions/:id/metrics/': MOCK_METRICS,
                '/api/projects/:project_id/event_definitions/primary_properties/': {
                    primary_properties: {},
                },
                '/api/projects/:project_id/object_media_previews/': [],
                '/api/projects/:project_id/experiments/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const EventDefinitionMetadata: Story = {}

export const PropertyDefinitionQueryUsage: Story = {
    parameters: {
        pageUrl: urls.propertyDefinition(MOCK_PROPERTY_DEFINITION.id),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/property_definitions/:id/': MOCK_PROPERTY_DEFINITION,
                '/api/projects/:project_id/property_definitions/:id/usage/': MOCK_PROPERTY_USAGE,
                '/api/projects/:project_id/insights/': MOCK_PROPERTY_INSIGHTS,
            },
        }),
    ],
}
