import type { Meta, StoryObj } from '@storybook/react'

import { PersonFirstSeenCell } from './PersonFirstSeenCell'

const meta: Meta<typeof PersonFirstSeenCell> = {
    title: 'Scenes-App/AI observability/People/Person first seen cell',
    component: PersonFirstSeenCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        firstSeen: { firstSeen: '2026-11-12T12:30:00Z', checkedFrom: '2026-10-26', isNew: false },
        status: 'ready',
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-32">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof PersonFirstSeenCell>

export const FirstSeen: Story = {}

export const NewPerson: Story = {
    args: { firstSeen: { firstSeen: '2026-11-24T12:30:00Z', checkedFrom: '2026-10-26', isNew: true } },
}

export const NothingSinceCheckedDate: Story = {
    args: { firstSeen: { firstSeen: null, checkedFrom: '2026-10-26', isNew: true } },
}

export const Loading: Story = { args: { firstSeen: null, status: 'loading' } }

export const Failed: Story = { args: { firstSeen: null, status: 'error' } }
