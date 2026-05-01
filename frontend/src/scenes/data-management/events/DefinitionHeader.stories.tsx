import { Meta, StoryFn } from '@storybook/react'

import { EventDefinition, PropertyDefinition } from '~/types'

import {
    getEventDefinitionIcon,
    getEventMetadataDefinitionIcon,
    getRevenueAnalyticsDefinitionIcon,
} from './DefinitionHeader'

const meta: Meta = {
    title: 'Components/Definition Icons',
    tags: ['autodocs'],
}
export default meta

function IconGrid({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex flex-col gap-3 p-4">{children}</div>
}

function IconRow({
    label,
    expectedIcon,
    children,
}: {
    label: string
    expectedIcon: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex items-center gap-4">
            <span className="w-40 font-mono text-xs">{expectedIcon}</span>
            <span className="w-48 text-xs text-muted">{label}</span>
            <span className="text-2xl">{children}</span>
        </div>
    )
}

function makeEventDefinition(
    overrides: Partial<EventDefinition> & { value?: string | null } & Pick<EventDefinition, 'name'>
): EventDefinition & { value?: string | null } {
    return {
        id: 'b1e29c4a-7d3f-4a8e-9b2d-1c5f6e8a0d3b',
        ...overrides,
    }
}

function makePropertyDefinition(
    overrides: Partial<PropertyDefinition> & Pick<PropertyDefinition, 'name'>
): PropertyDefinition {
    return {
        id: 'a2f38d5b-6e1c-4b9a-8c7d-2d4e5f6a7b8c',
        ...overrides,
    }
}

const EVENT_ICON_CASES: {
    label: string
    expectedIcon: string
    definition: EventDefinition & { value?: string | null }
}[] = [
    {
        label: '$pageview',
        expectedIcon: 'IconEye',
        definition: makeEventDefinition({ name: '$pageview' }),
    },
    {
        label: '$screen',
        expectedIcon: 'IconEye',
        definition: makeEventDefinition({ name: '$screen' }),
    },
    {
        label: '$pageleave',
        expectedIcon: 'IconLeave',
        definition: makeEventDefinition({ name: '$pageleave' }),
    },
    {
        label: '$autocapture',
        expectedIcon: 'IconBolt',
        definition: makeEventDefinition({ name: '$autocapture' }),
    },
    {
        label: '$identify (core PostHog event)',
        expectedIcon: 'IconLogomark',
        definition: makeEventDefinition({ name: '$identify' }),
    },
    {
        label: 'All events (value=null)',
        expectedIcon: 'IconSelectAll',
        definition: makeEventDefinition({ name: 'all_events', value: null }),
    },
    {
        label: 'Action',
        expectedIcon: 'IconPlay',
        definition: makeEventDefinition({ name: 'my_action', is_action: true }),
    },
    {
        label: 'Data warehouse event',
        expectedIcon: 'IconServer',
        definition: makeEventDefinition({ name: 'warehouse_event', is_data_warehouse: true }),
    },
    {
        label: 'Custom event (sign_up)',
        expectedIcon: 'IconCursor',
        definition: makeEventDefinition({ name: 'sign_up' }),
    },
    {
        label: '$pageview (verified)',
        expectedIcon: 'IconEye + badge',
        definition: makeEventDefinition({ name: '$pageview', verified: true }),
    },
    {
        label: '$pageview (hidden)',
        expectedIcon: 'IconEye + badge',
        definition: makeEventDefinition({ name: '$pageview', hidden: true }),
    },
]

export const EventDefinitionIcons: StoryFn = () => (
    <IconGrid>
        {EVENT_ICON_CASES.map(({ label, expectedIcon, definition }) => (
            <IconRow key={label} label={label} expectedIcon={expectedIcon}>
                {getEventDefinitionIcon(definition)}
            </IconRow>
        ))}
    </IconGrid>
)

const EVENT_METADATA_CASES: { label: string; expectedIcon: string; definition: PropertyDefinition }[] = [
    {
        label: 'distinct_id (core metadata)',
        expectedIcon: 'IconLogomark',
        definition: makePropertyDefinition({ name: 'distinct_id' }),
    },
    {
        label: 'timestamp (core metadata)',
        expectedIcon: 'IconLogomark',
        definition: makePropertyDefinition({ name: 'timestamp' }),
    },
    {
        label: 'custom_property',
        expectedIcon: 'IconList',
        definition: makePropertyDefinition({ name: 'custom_property' }),
    },
]

export const EventMetadataDefinitionIcons: StoryFn = () => (
    <IconGrid>
        {EVENT_METADATA_CASES.map(({ label, expectedIcon, definition }) => (
            <IconRow key={label} label={label} expectedIcon={expectedIcon}>
                {getEventMetadataDefinitionIcon(definition)}
            </IconRow>
        ))}
    </IconGrid>
)

const REVENUE_ANALYTICS_CASES: { label: string; expectedIcon: string; definition: PropertyDefinition }[] = [
    {
        label: 'revenue_analytics_customer.email',
        expectedIcon: 'IconLogomark',
        definition: makePropertyDefinition({ name: 'revenue_analytics_customer.email' }),
    },
    {
        label: 'revenue_analytics_product.name',
        expectedIcon: 'IconLogomark',
        definition: makePropertyDefinition({ name: 'revenue_analytics_product.name' }),
    },
    {
        label: 'custom_field',
        expectedIcon: 'IconList',
        definition: makePropertyDefinition({ name: 'custom_field' }),
    },
]

export const RevenueAnalyticsDefinitionIcons: StoryFn = () => (
    <IconGrid>
        {REVENUE_ANALYTICS_CASES.map(({ label, expectedIcon, definition }) => (
            <IconRow key={label} label={label} expectedIcon={expectedIcon}>
                {getRevenueAnalyticsDefinitionIcon(definition)}
            </IconRow>
        ))}
    </IconGrid>
)
