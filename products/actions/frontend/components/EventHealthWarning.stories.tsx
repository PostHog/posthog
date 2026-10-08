import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { EventHealthWarning } from './EventHealthWarning'

const meta: Meta<typeof EventHealthWarning> = {
    title: 'Components/Event Health Warning',
    component: EventHealthWarning,
    parameters: {
        mockDate: '2023-02-15',
        docs: {
            description: {
                component:
                    'Warns that the event an action match group points at stopped arriving, so the group quietly matches nothing new. Steps are OR-ed, so the rest of the action keeps matching. Shown on the actions list next to the group it affects, and in the step editor. Nothing renders while the event definition is still loading, or when the event is healthy.',
            },
        },
    },
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
    tags: ['autodocs'],
}
export default meta
type Story = StoryObj<typeof EventHealthWarning>

const VARIANTS: { label: string; event: string | null }[] = [
    { label: 'Healthy event, nothing is shown', event: 'purchase_completed' },
    { label: 'Event last seen months ago', event: 'trial_started' },
    { label: 'Event with no definition, deleted or never sent', event: 'checkout_abandoned' },
    { label: 'Step that matches all events', event: null },
]

export const Variants: Story = {
    render: () => (
        <div className="flex flex-col gap-2 max-w-2xl">
            {VARIANTS.map(({ label, event }) => (
                <div key={label} className="flex items-center gap-2 border rounded p-2 bg-surface-primary">
                    <span className="text-xs text-secondary w-80 shrink-0">{label}</span>
                    <span className="font-mono text-xs">{event ?? 'All events'}</span>
                    <EventHealthWarning event={event} />
                </div>
            ))}
        </div>
    ),
}
