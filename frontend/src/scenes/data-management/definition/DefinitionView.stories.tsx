import { MOCK_SECOND_BASIC_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const EVENT_DEFINITION_PATH = '/api/projects/:project_id/event_definitions/:id/'

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
    id: '0190c3a1-1f2e-7000-8000-000000000001',
    name: 'plan_tier',
    description: 'Subscription tier at the time of the event',
    tags: [],
    is_numerical: false,
    property_type: 'String',
    type: 'event',
    updated_at: '2026-04-15T10:00:00Z',
    updated_by: null,
    verified: false,
    hidden: false,
}

const MOCK_USER = { id: 1, uuid: '0190c3a1-1f2e-7000-8000-0000000000aa', first_name: 'Demo', email: 'demo@posthog.com' }

function mockInsight(
    id: number,
    name: string,
    kind: 'TrendsQuery' | 'FunnelsQuery',
    dashboardIds: number[],
    lastViewedAt: string | null
): Record<string, unknown> {
    return {
        id,
        short_id: `ins${id}`,
        name,
        derived_name: null,
        description: null,
        query: { kind: 'InsightVizNode', source: { kind, series: [] } },
        dashboard_tiles: dashboardIds.map((dashboardId) => ({ id: id * 10 + dashboardId, dashboard_id: dashboardId })),
        created_by: MOCK_USER,
        created_at: '2026-01-10T09:00:00Z',
        last_modified_at: '2026-04-20T12:00:00Z',
        last_viewed_at: lastViewedAt,
        saved: true,
        tags: [],
    }
}

const MOCK_INSIGHTS = [
    mockInsight(1, 'Revenue by plan tier', 'TrendsQuery', [1, 2], '2026-04-29T08:00:00Z'),
    mockInsight(2, 'Upgrade funnel by plan tier', 'FunnelsQuery', [2], '2026-04-12T15:30:00Z'),
    mockInsight(3, 'Weekly active users by plan tier', 'TrendsQuery', [], null),
]

function propertyUsageDecorator(
    queryUsage: number,
    insights: Record<string, unknown>[]
): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:project_id/property_definitions/:id/': MOCK_PROPERTY_DEFINITION,
            '/api/projects/:project_id/insights/': {
                count: insights.length,
                next: null,
                previous: null,
                results: insights,
            },
        },
        post: {
            '/api/projects/:project_id/property_definitions/usage_metrics/': {
                results: [
                    {
                        type: 'event',
                        name: MOCK_PROPERTY_DEFINITION.name,
                        group_type_index: null,
                        query_usage_30_day: queryUsage,
                    },
                ],
            },
        },
    })
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Definition View',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-04-30',
        pageUrl: urls.eventDefinition(MOCK_EVENT_DEFINITION.id),
        // The full DefinitionView mounts EventDefinitionProperties / EventDefinitionInsights / a
        // matching-events table — those keep their loaders spinning because we don't mock every
        // downstream endpoint. The metadata row (Owner + Status + Primary property) is what this story
        // exists to capture, so don't block on loaders that are intentionally never going to settle.
        testOptions: {
            waitForLoadersToDisappear: false,
            viewportWidths: ['narrow', 'medium', 'wide', 'superwide'],
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [EVENT_DEFINITION_PATH]: MOCK_EVENT_DEFINITION,
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

const withOwner = mswDecorator({
    get: { [EVENT_DEFINITION_PATH]: { ...MOCK_EVENT_DEFINITION, owner: MOCK_SECOND_BASIC_USER } },
})

export const EventDefinitionWithOwner: Story = {
    decorators: [withOwner],
}

export const EventDefinitionEditWithOwner: Story = {
    parameters: { pageUrl: urls.eventDefinitionEdit(MOCK_EVENT_DEFINITION.id) },
    decorators: [withOwner],
}

export const PropertyDefinitionUsage: Story = {
    parameters: {
        pageUrl: urls.propertyDefinition(MOCK_PROPERTY_DEFINITION.id),
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [propertyUsageDecorator(4821, MOCK_INSIGHTS)],
}

export const PropertyDefinitionUsageEmpty: Story = {
    parameters: {
        pageUrl: urls.propertyDefinition(MOCK_PROPERTY_DEFINITION.id),
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [propertyUsageDecorator(0, [])],
}
