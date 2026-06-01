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
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const EventDefinitionMetadata: Story = {}
