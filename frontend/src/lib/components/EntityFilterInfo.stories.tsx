import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
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

const HEALTH_VARIANTS: { label: string; filter: EntityFilter | ActionFilter }[] = [
    {
        label: 'Event PostHog still sees',
        filter: { type: EntityTypes.EVENTS, id: 'purchase_completed', name: 'purchase_completed' },
    },
    {
        label: 'Event last seen months ago',
        filter: { type: EntityTypes.EVENTS, id: 'trial_started', name: 'trial_started' },
    },
    {
        label: 'Event with no definition, deleted or never sent',
        filter: { type: EntityTypes.EVENTS, id: 'checkout_abandoned', name: 'checkout_abandoned' },
    },
    {
        label: 'Renamed series on a dead event',
        filter: { type: EntityTypes.EVENTS, id: 'trial_started', name: 'trial_started', custom_name: 'Trials' },
    },
    {
        label: 'Action series, health is not asked about',
        filter: { type: EntityTypes.ACTIONS, id: 5, name: 'Completed purchase' },
    },
]

export const EventHealthOnSeries: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/event_definitions/': {
                    count: 2,
                    results: [
                        { id: '1', name: 'purchase_completed', last_seen_at: '2023-02-14T10:00:00Z' },
                        { id: '2', name: 'trial_started', last_seen_at: '2022-11-01T10:00:00Z' },
                    ],
                },
            },
        }),
    ],
    parameters: {
        mockDate: '2023-02-15',
        docs: {
            description: {
                story: 'With `showEventHealth`, a series whose event stopped arriving carries a warning icon, so an insight charting a flat zero says why. Hovering the icon says when PostHog last saw the event. Healthy events and action series stay plain.',
            },
        },
    },
    render: () => (
        <div className="flex flex-col gap-2 max-w-2xl">
            {HEALTH_VARIANTS.map(({ label, filter }) => (
                <div key={label} className="flex items-center gap-4 border rounded p-2 bg-surface-primary">
                    <span className="text-xs text-secondary w-80 shrink-0">{label}</span>
                    <EntityFilterInfo filter={filter} showEventHealth />
                </div>
            ))}
        </div>
    ),
}
