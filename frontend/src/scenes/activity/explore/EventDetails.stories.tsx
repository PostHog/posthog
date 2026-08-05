import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { EventType } from '~/types'

import { EventDetails } from './EventDetails'

// An event whose properties include nested objects and arrays — the case that regressed to
// rendering fully expanded inline. These call sites now pass `collapsible`, so the nested
// values should render as collapsed JSON viewers rather than expanded nested tables.
const eventWithNestedProperties: EventType = {
    id: '0192a5c8-0000-0000-0000-000000000000',
    uuid: '0192a5c8-0000-0000-0000-000000000000',
    distinct_id: 'user-42',
    event: 'checkout_completed',
    timestamp: '2023-01-28T10:00:00.000Z',
    elements: [],
    properties: {
        order_total: 129.99,
        currency: 'USD',
        coupon: 'WELCOME10',
        billing: {
            plan: 'enterprise',
            seats: 42,
            features: { sso: true, audit_log: true, sla: '99.99%' },
        },
        line_items: [
            { sku: 'SKU-001', name: 'Widget', qty: 2, price: 19.99 },
            { sku: 'SKU-002', name: 'Gadget', qty: 1, price: 89.99 },
            { sku: 'SKU-003', name: 'Sticker pack', qty: 1, price: 0 },
        ],
        experiment_variants: ['pricing-v3', 'checkout-express', 'new-nav'],
    },
}

const meta: Meta<typeof EventDetails> = {
    component: EventDetails,
    title: 'Components/EventDetails',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/event_definitions/primary_properties/': { primary_properties: {} },
            },
        }),
    ],
    parameters: {
        mockDate: '2023-01-28',
        // The collapsed nested values render in a lazily-loaded JSON viewer; wait for it to mount
        // so the snapshot captures the collapsed viewer rather than its loading skeleton.
        testOptions: { waitForSelector: '.react-json-view' },
    },
}
export default meta

type Story = StoryObj<typeof EventDetails>

export const NestedProperties: Story = {
    render: () => (
        <div className="w-[40rem]">
            <EventDetails event={eventWithNestedProperties} />
        </div>
    ),
}
