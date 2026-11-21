import { MOCK_SECOND_BASIC_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
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

// 30 days ending on the story's mockDate, so the sparkline labels stay fixed.
const MOCK_DAYS = Array.from({ length: 30 }, (_, index) =>
    new Date(Date.UTC(2026, 3, 1 + index)).toISOString().slice(0, 10)
)

function mockDailyCounts(base: number): number[] {
    return MOCK_DAYS.map((_, index) => Math.round(base * (1 + 0.4 * Math.sin(index / 2.5))))
}

function mockQueryUsage(base: number, previous: number | null): Record<string, unknown> {
    const counts = mockDailyCounts(base)
    return {
        query_usage_30_day: counts.reduce((total, count) => total + count, 0),
        query_usage_previous_30_day: previous,
        query_usage_daily: MOCK_DAYS.map((date, index) => ({ date, count: counts[index] })),
    }
}

function mockEventVolumeResponse(base: number, previousBase: number): Record<string, unknown> {
    const result = (compareLabel: 'current' | 'previous', counts: number[]): Record<string, unknown> => ({
        label: 'All events',
        count: counts.reduce((total, count) => total + count, 0),
        data: counts,
        days: MOCK_DAYS,
        labels: MOCK_DAYS,
        compare: true,
        compare_label: compareLabel,
    })
    return { results: [result('current', mockDailyCounts(base)), result('previous', mockDailyCounts(previousBase))] }
}

// The event page has no usage before the earlier window, so it shows no comparison.
const MOCK_METRICS = mockQueryUsage(410, null)

const MOCK_PROPERTY_DEFINITION = {
    id: '0190c3a1-1f2e-7000-8000-000000000001',
    name: 'plan_tier',
    description: 'Subscription tier at the time of the event',
    tags: [],
    is_numerical: false,
    property_type: 'String',
    type: 'event',
    group_type_index: null,
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
    { ...mockInsight(3, 'Weekly active users by plan tier', 'TrendsQuery', [], null), created_by: null },
]

const MOCK_EVENT_INSIGHTS = [
    mockInsight(4, 'Orders placed per day', 'TrendsQuery', [1], '2026-04-28T09:00:00Z'),
    mockInsight(5, 'Checkout to order funnel', 'FunnelsQuery', [1, 3], '2026-04-21T11:15:00Z'),
    { ...mockInsight(6, 'Orders by country', 'TrendsQuery', [], null), created_by: null },
]

function insightsListMock(insights: Record<string, unknown>[]): Record<string, unknown> {
    return { count: insights.length, next: null, previous: null, results: insights }
}

function propertyUsageDecorator(
    queryUsage: Record<string, unknown>,
    eventVolume: Record<string, unknown>,
    insights: Record<string, unknown>[]
): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:project_id/property_definitions/:id/': MOCK_PROPERTY_DEFINITION,
            '/api/projects/:project_id/insights/': insightsListMock(insights),
        },
        post: {
            '/api/projects/:project_id/property_definitions/usage_metrics/': {
                results: [
                    { type: 'event', name: MOCK_PROPERTY_DEFINITION.name, group_type_index: null, ...queryUsage },
                ],
            },
            '/api/environments/:team_id/query/': eventVolume,
            '/api/environments/:team_id/query/:query_kind/': eventVolume,
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
        featureFlags: [FEATURE_FLAGS.DEFINITION_USAGE_SECTION],
        // The event page's properties and matching-events loaders never settle because their endpoints are not mocked.
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

export const EventDefinitionMetadata: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/insights/': insightsListMock(MOCK_EVENT_INSIGHTS),
            },
        }),
    ],
}

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
    decorators: [
        propertyUsageDecorator(mockQueryUsage(160, 3900), mockEventVolumeResponse(52000, 61000), MOCK_INSIGHTS),
    ],
}

export const PropertyDefinitionUsageEmpty: Story = {
    parameters: {
        pageUrl: urls.propertyDefinition(MOCK_PROPERTY_DEFINITION.id),
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [propertyUsageDecorator(mockQueryUsage(0, 0), mockEventVolumeResponse(0, 0), [])],
}
