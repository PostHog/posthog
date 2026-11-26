import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { CoreEvent, CoreEventCategory, NodeKind } from '~/queries/schema/schema-general'

const MOCK_CORE_EVENTS: CoreEvent[] = [
    {
        id: 'core-event-1',
        name: 'Signed up',
        category: CoreEventCategory.Acquisition,
        filter: { kind: NodeKind.EventsNode, event: 'user signed up' },
    },
    {
        id: 'core-event-2',
        name: 'Purchased',
        description: 'A completed checkout',
        category: CoreEventCategory.Monetization,
        filter: { kind: NodeKind.ActionsNode, id: 1, name: 'Completed checkout' },
    },
    {
        id: 'core-event-3',
        name: 'Subscription started',
        category: CoreEventCategory.Monetization,
        filter: {
            kind: NodeKind.DataWarehouseNode,
            id: 'stripe_subscriptions',
            table_name: 'stripe_subscriptions',
            id_field: 'id',
            timestamp_field: 'created_at',
            distinct_id_field: 'customer_email',
        },
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Core Events',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15',
        pageUrl: urls.coreEvents(),
        featureFlags: [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForSelector: 'text=Subscription started', snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/core_events/': toPaginatedResponse(MOCK_CORE_EVENTS),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const CoreEventsQuill: Story = {}
