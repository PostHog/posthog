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
// A failing model is what brings someone to this page, and a database exception is rarely one
// line. This is the case the card has to hold without pushing the tabs off screen.
const LONG_ERROR = [
    'ClickHouse error: Code 241. DB::Exception: Memory limit (total) exceeded.',
    ...Array.from({ length: 40 }, (_, index) => `  at step ${index + 1} of the query plan`),
].join('\n')

export const LongError: Story = { args: { status: 'Failed', error: LONG_ERROR } }
export const Running: Story = { args: { status: 'Running' } }
export const FirstRun: Story = { args: { status: null, lastSuccessfulSyncAt: null } }
export const Loading: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
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

export const StaleHistory: Story = {
    args: { historyError: true, onRetry: () => undefined },
}
