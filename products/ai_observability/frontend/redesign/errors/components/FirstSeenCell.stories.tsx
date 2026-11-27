import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { FirstSeenCell } from './FirstSeenCell'

const meta: Meta<typeof FirstSeenCell> = {
    title: 'Scenes-App/AI observability/Errors/First seen cell',
    component: FirstSeenCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        timezone: 'UTC',
        load: {
            status: 'ready',
            value: { firstSeen: '2026-09-02T08:30:00Z', checkedFrom: '2026-08-02', isNew: false },
        },
    },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof FirstSeenCell>

export const FirstSeen: Story = {}

export const NothingSinceCheckedDate: Story = {
    args: { load: { status: 'ready', value: { firstSeen: null, checkedFrom: '2026-08-02', isNew: false } } },
}

export const Loading: Story = { args: { load: { status: 'loading' } } }

export const Failed: Story = { args: { load: { status: 'error' } } }
