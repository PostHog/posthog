import '../Bets.scss'

import type { Meta, StoryObj } from '@storybook/react'

import 'scenes/project-homepage/today/Today.scss'

import { BetActivity } from './BetActivity'

const meta: Meta<typeof BetActivity> = {
    title: 'Products/Bets/Activity',
    component: BetActivity,
    decorators: [
        (Story) => (
            <div className="Today Bets Today__page p-6" data-quill>
                <Story />
            </div>
        ),
    ],
    args: {
        loading: false,
        error: null,
        onRefresh: () => {},
        entries: [
            {
                id: 'flag',
                at: '2026-10-24T10:00:00Z',
                title: 'Feature flag enabled',
                detail: 'Remember export settings',
                resource: 'flag',
                resource_id: '2',
            },
            {
                id: 'task',
                at: '2026-10-24T09:00:00Z',
                title: 'Task completed',
                detail: 'Preserve the selected export format',
                resource: 'task',
                resource_id: 'example-task',
            },
            {
                id: 'budget',
                at: '2026-10-24T08:00:00Z',
                title: 'Budget allocated',
                detail: '$100.00',
                resource: '',
                resource_id: '',
            },
        ],
    },
}
export default meta
type Story = StoryObj<typeof meta>
export const RecordedEvents: Story = {}
export const Loading: Story = { args: { entries: null, loading: true } }
export const Error: Story = { args: { entries: null, error: 'Could not load activity. Try again.' } }
export const Empty: Story = { args: { entries: [] } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div style={{ width: 520 }}>
                <Story />
            </div>
        ),
    ],
}
