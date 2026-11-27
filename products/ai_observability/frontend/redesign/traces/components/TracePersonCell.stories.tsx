import type { Meta, StoryObj } from '@storybook/react'

import { TracePersonCell } from './TracePersonCell'

const meta: Meta<typeof TracePersonCell> = {
    title: 'Scenes-App/AI observability/Traces/Trace person cell',
    component: TracePersonCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { person: { distinctId: 'user-4821', label: 'Ana Example' }, status: 'ready' },
}
export default meta

type Story = StoryObj<typeof TracePersonCell>

export const NamedPerson: Story = {}

export const EmailLabel: Story = {
    args: { person: { distinctId: 'ana@example.com', label: 'ana@example.com' } },
}

export const DistinctIdOnly: Story = {
    args: {
        person: {
            distinctId: '0192f3c9-a1d2-7b4e-9c8f-5e6d7a8b9c0d',
            label: '0192f3c9-a1d2-7b4e-9c8f-5e6d7a8b9c0d',
        },
    },
}

export const Loading: Story = { args: { status: 'loading' } }

export const Failed: Story = { args: { status: 'error' } }

export const NoPerson: Story = { args: { person: null } }

export const NarrowContainer: Story = {
    args: {
        person: {
            distinctId: 'a.very.long.address.for.truncation@example.com',
            label: 'a.very.long.address.for.truncation@example.com',
        },
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-32">
                <StoryComponent />
            </div>
        ),
    ],
}
