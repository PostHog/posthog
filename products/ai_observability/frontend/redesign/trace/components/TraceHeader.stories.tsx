import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { TraceHeader } from './TraceHeader'

const meta: Meta<typeof TraceHeader> = {
    title: 'Scenes-App/AI observability/Trace view/Trace header',
    component: TraceHeader,
    args: {
        name: 'answer-billing-question',
        hasError: false,
        olderHref: '/older',
        newerHref: null,
        backLink: { label: 'Back to traces', href: '/traces' },
    },
}
export default meta

type Story = StoryObj<typeof TraceHeader>

const exportAction = { loading: false, onExport: () => {} }

export const Default: Story = {}
export const Errored: Story = { args: { hasError: true } }
export const WithExport: Story = { args: { exportAction } }
export const ExportInProgress: Story = {
    args: { exportAction: { ...exportAction, loading: true } },
    // The busy button's spinner is the state this story shows, so the snapshot must not wait for it to go.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const WithSearch: Story = {
    args: {
        search: {
            query: 'seats',
            status: 'ready',
            total: 3,
            matchingSteps: 2,
            position: 1,
            failure: null,
            onQueryChange: () => {},
            onStep: () => {},
        },
    },
}
export const Narrow: Story = {
    args: { name: 'a-very-long-trace-name-that-should-truncate-cleanly', exportAction },
    decorators: [withWidth(360)],
}
