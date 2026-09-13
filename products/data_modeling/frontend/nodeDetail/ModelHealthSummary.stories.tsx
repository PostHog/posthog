import type { Meta, StoryObj } from '@storybook/react'

import { ModelHealthSummary } from './ModelHealthSummary'

const meta: Meta<typeof ModelHealthSummary> = {
    title: 'Products/Data modeling/Model health summary',
    component: ModelHealthSummary,
    args: {
        status: 'Completed',
        suspended: false,
        lastSuccessfulSyncAt: '2026-09-12T10:00:00Z',
        historyLoaded: true,
        schedule: 'Every 1 hour',
        lineageUrl: '#lineage',
        downstreamCount: 3,
    },
    parameters: { testOptions: { snapshotBrowsers: ['chromium'] } },
}
export default meta

type Story = StoryObj<typeof ModelHealthSummary>

export const Completed: Story = {}
export const Failed: Story = {
    args: { status: 'Failed', error: 'The query could not finish because its memory limit was exceeded.' },
}
export const Suspended: Story = {
    args: {
        status: 'Failed',
        suspended: true,
        schedule: 'Suspended after repeated failures',
        error: 'The source table orders is unavailable.',
    },
}
export const Running: Story = { args: { status: 'Running' } }
export const FirstRun: Story = { args: { status: null, lastSuccessfulSyncAt: null } }
export const Loading: Story = {
    args: { status: null, lastSuccessfulSyncAt: null, historyLoaded: false, schedule: null },
}
export const Narrow: Story = {
    ...Suspended,
    decorators: [
        (StoryFn) => (
            <div className="w-128">
                <StoryFn />
            </div>
        ),
    ],
}
