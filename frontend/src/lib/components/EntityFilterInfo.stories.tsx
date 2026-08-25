import { Meta, StoryObj } from '@storybook/react'

import { ActionFilter, EntityFilter, EntityTypes } from '~/types'

import { EntityFilterInfo } from './EntityFilterInfo'

const meta: Meta<typeof EntityFilterInfo> = {
    title: 'Components/Entity Filter Info',
    component: EntityFilterInfo,
    parameters: {
        docs: {
            description: {
                component:
                    'Renders an insight series label. When the series is renamed (via `custom_name`, or a `name` set through the API) the label alone hides what the series queries, so the underlying entity is revealed as secondary text plus an "Event sent as …" tooltip on hover.',
            },
        },
    },
    tags: ['autodocs'],
}
export default meta
type Story = StoryObj<typeof EntityFilterInfo>

const VARIANTS: { label: string; filter: EntityFilter | ActionFilter }[] = [
    {
        label: 'Unrenamed core event (single label, no tooltip)',
        filter: { type: EntityTypes.EVENTS, id: '$pageview', name: '$pageview' },
    },
    {
        label: 'Unrenamed custom event',
        filter: { type: EntityTypes.EVENTS, id: 'signed up', name: 'signed up' },
    },
    {
        label: 'Renamed via custom name — hover for the tooltip',
        filter: { type: EntityTypes.EVENTS, id: 'signed up', name: 'signed up', custom_name: 'Completed sign-up' },
    },
    {
        label: 'Renamed via name (set through the API) — hover for the tooltip',
        filter: { type: EntityTypes.EVENTS, id: '$pageview', name: 'Visited posthog.com' },
    },
    {
        label: 'Renamed action — hover for the tooltip',
        filter: { type: EntityTypes.ACTIONS, id: 5, name: 'Completed purchase', custom_name: 'Checkout' },
    },
    {
        label: 'Renamed all-events series',
        filter: { type: EntityTypes.EVENTS, id: null, name: 'All events', custom_name: 'Total traffic' },
    },
]

export const RenamedAndUnrenamedSeries: Story = {
    render: () => (
        <div className="flex flex-col gap-2 max-w-2xl">
            {VARIANTS.map(({ label, filter }) => (
                <div key={label} className="flex items-center gap-4 border rounded p-2 bg-surface-primary">
                    <span className="text-xs text-secondary w-80 shrink-0">{label}</span>
                    <EntityFilterInfo filter={filter} />
                </div>
            ))}
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'Renamed series show the underlying entity as secondary text; hovering the label opens a tooltip with the raw key ("Event sent as `signed up`"). Unrenamed series keep a single plain label with no tooltip.',
            },
        },
    },
}
