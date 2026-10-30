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

export const Default: Story = {}
export const Errored: Story = { args: { hasError: true } }
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
    args: { name: 'a-very-long-trace-name-that-should-truncate-cleanly' },
    decorators: [withWidth(360)],
}
