import { Meta, StoryFn } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { CoreEventCategory, NodeKind } from '~/queries/schema/schema-general'

import { CATEGORY_OPTIONS, CategorySection, CoreEventCard } from './CoreEventComponents'
import { CoreEventsSettings } from './CoreEventsSettings'

const meta: Meta = {
    title: 'Scenes-App/Settings/Environment/Core Events',
    parameters: {
        layout: 'padded',
    },
}
export default meta

const mockEvents = [
    {
        id: 'event-1',
        name: 'Sign Up',
        description: 'User created an account',
        category: CoreEventCategory.Acquisition,
        filter: { kind: NodeKind.EventsNode, event: 'signed_up' },
    },
    {
        id: 'event-2',
        name: 'First Purchase',
        description: 'User completed their first purchase',
        category: CoreEventCategory.Activation,
        filter: { kind: NodeKind.EventsNode, event: 'purchase_completed' },
    },
    {
        id: 'event-3',
        name: 'Subscription Started',
        category: CoreEventCategory.Monetization,
        filter: { kind: NodeKind.ActionsNode, id: 123, name: 'Subscription Started' },
    },
    {
        id: 'event-4',
        name: 'Plan Upgraded',
        description: 'User upgraded their subscription plan',
        category: CoreEventCategory.Expansion,
        filter: { kind: NodeKind.EventsNode, event: 'plan_upgraded' },
    },
    {
        id: 'event-5',
        name: 'Invite Sent',
        category: CoreEventCategory.Referral,
        filter: { kind: NodeKind.EventsNode, event: 'invite_sent' },
    },
]

export const CoreEventCardWithDescription: StoryFn = () => {
    return (
        <CoreEventCard
            event={{
                id: 'event-1',
                name: 'Purchase Completed',
                description: 'User completed a purchase in the checkout flow',
                category: CoreEventCategory.Monetization,
                filter: { kind: NodeKind.EventsNode, event: 'purchase_completed' },
            }}
            onEdit={() => {}}
            onRemove={() => {}}
        />
    )
}

export const CoreEventCardWithoutDescription: StoryFn = () => {
    return (
        <CoreEventCard
            event={{
                id: 'event-1',
                name: 'Sign Up',
                category: CoreEventCategory.Acquisition,
                filter: { kind: NodeKind.EventsNode, event: 'signed_up' },
            }}
            onEdit={() => {}}
            onRemove={() => {}}
        />
    )
}

export const CoreEventCardAction: StoryFn = () => {
    return (
        <CoreEventCard
            event={{
                id: 'event-1',
                name: 'Checkout Completed',
                description: 'Action that tracks checkout completions',
                category: CoreEventCategory.Monetization,
                filter: { kind: NodeKind.ActionsNode, id: 123, name: 'Checkout Action' },
            }}
            onEdit={() => {}}
            onRemove={() => {}}
        />
    )
}

export const CoreEventCardDataWarehouse: StoryFn = () => {
    return (
        <CoreEventCard
            event={{
                id: 'event-1',
                name: 'Revenue from Stripe',
                description: 'Revenue data imported from Stripe',
                category: CoreEventCategory.Monetization,
                filter: {
                    kind: NodeKind.DataWarehouseNode,
                    id: 'stripe_charges',
                    table_name: 'stripe_charges',
                    id_field: 'id',
                    timestamp_field: 'created_at',
                    distinct_id_field: 'customer_id',
                },
            }}
            onEdit={() => {}}
            onRemove={() => {}}
        />
    )
}

export const CategorySectionWithEvents: StoryFn = () => {
    const monetizationCategory = CATEGORY_OPTIONS.find((c) => c.value === CoreEventCategory.Monetization)!
    return (
        <CategorySection
            category={monetizationCategory}
            events={[
                {
                    id: 'event-1',
                    name: 'First Purchase',
                    description: 'User completed their first purchase',
                    category: CoreEventCategory.Monetization,
                    filter: { kind: NodeKind.EventsNode, event: 'purchase_completed' },
                },
                {
                    id: 'event-2',
                    name: 'Subscription Started',
                    category: CoreEventCategory.Monetization,
                    filter: { kind: NodeKind.ActionsNode, id: 123, name: 'Subscription Action' },
                },
            ]}
            onEdit={() => {}}
            onRemove={() => {}}
            onAdd={() => {}}
        />
    )
}

export const CategorySectionEmpty: StoryFn = () => {
    const acquisitionCategory = CATEGORY_OPTIONS.find((c) => c.value === CoreEventCategory.Acquisition)!
    return (
        <CategorySection
            category={acquisitionCategory}
            events={[]}
            onEdit={() => {}}
            onRemove={() => {}}
            onAdd={() => {}}
        />
    )
}

export const FullSettingsWithEvents: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/core_events/': {
                results: mockEvents,
            },
        },
    })

    return <CoreEventsSettings />
}

export const FullSettingsEmpty: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/core_events/': {
                results: [],
            },
        },
    })

    return <CoreEventsSettings />
}
