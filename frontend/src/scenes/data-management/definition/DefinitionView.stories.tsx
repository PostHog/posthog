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

const MOCK_PERSON_PROPERTY_DEFINITION = {
    id: 'person-plan',
    name: 'plan',
    description: 'Subscription plan the person is on',
    tags: ['billing'],
    property_type: 'String',
    type: 'person',
    verified: true,
    verified_at: '2026-02-01T10:00:00Z',
    verified_by: { id: 1, first_name: 'Demo', email: 'demo@posthog.com' },
    hidden: false,
    updated_at: '2026-04-15T10:00:00Z',
    updated_by: { id: 1, first_name: 'Demo', email: 'demo@posthog.com' },
}

const MOCK_PERSON_PROPERTY_USED_IN = {
    insights: {
        results: [
            { id: 12, short_id: 'aBcD1234', name: 'Weekly active users by plan' },
            { id: 30, short_id: 'wXyZ7788', name: 'Revenue by plan tier' },
        ],
        total: 2,
        has_more: false,
    },
    cohorts: {
        results: [
            { id: 4, name: 'Pro plan users' },
            { id: 7, name: 'Enterprise accounts' },
        ],
        total: 2,
        has_more: false,
    },
    feature_flags: {
        results: [{ id: 21, key: 'pro-only-dashboard', name: 'Pro-only dashboard' }],
        total: 1,
        has_more: false,
    },
    experiments: { results: [{ id: 3, name: 'Pro onboarding checklist' }], total: 1, has_more: false },
    surveys: { results: [{ id: 'srv-1', name: 'Enterprise NPS survey' }], total: 1, has_more: false },
    hog_functions: {
        results: [{ id: 'fn-1', name: 'Sync plan to Salesforce' }],
        total: 1,
        has_more: false,
    },
    hog_flows: { results: [{ id: 'flow-1', name: 'Upgrade nudge workflow' }], total: 1, has_more: false },
}

const MOCK_PERSON_PROPERTY_USAGE_SUMMARY = {
    profiles_total: 24500,
    results: [
        {
            name: 'plan',
            usage: {
                insights: 2,
                cohorts: 2,
                feature_flags: 1,
                experiments: 1,
                surveys: 1,
                hog_functions: 1,
                hog_flows: 1,
            },
            total_usage: 9,
            profiles_percentage: 78.4,
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
        featureFlags: ['promoted-event-properties-edit'],
        // The full DefinitionView mounts EventDefinitionProperties / EventDefinitionInsights / a
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
                // usage_summary must precede the :id handler — MSW first-matches, and ':id' would
                // otherwise capture the literal "usage_summary" path segment.
                '/api/projects/:project_id/property_definitions/usage_summary/': MOCK_PERSON_PROPERTY_USAGE_SUMMARY,
                '/api/projects/:project_id/property_definitions/:id/used_in/': MOCK_PERSON_PROPERTY_USED_IN,
                '/api/projects/:project_id/property_definitions/:id/metrics/': MOCK_METRICS,
                '/api/projects/:project_id/property_definitions/:id/': MOCK_PERSON_PROPERTY_DEFINITION,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const EventDefinitionMetadata: Story = {}

export const PersonPropertyUsedIn: Story = {
    parameters: {
        pageUrl: urls.propertyDefinition(MOCK_PERSON_PROPERTY_DEFINITION.id),
    },
}
