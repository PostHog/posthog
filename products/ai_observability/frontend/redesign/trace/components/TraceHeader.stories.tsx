import type { Meta, StoryObj } from '@storybook/react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { withWidth } from '../storyFixtures'
import { TraceHeader } from './TraceHeader'

const meta: Meta<typeof TraceHeader> = {
    title: 'Scenes-App/AI observability/Trace view/Trace header',
    component: TraceHeader,
    // The header is an inline-size container, which contributes no intrinsic width, so an unsized story root collapses
    // to zero. Stories that pin their own width nest inside this one.
    decorators: [withWidth(1100)],
    args: {
        name: 'answer-billing-question',
        hasError: false,
        backLink: { label: 'Back to traces', href: '/traces' },
    },
}
export default meta

type Story = StoryObj<typeof TraceHeader>

const exportAction = { loading: false, onExport: () => {} }
const copyAction = { loading: false, onCopy: () => {} }

export const Default: Story = {}
export const Errored: Story = { args: { hasError: true } }
export const WithExport: Story = { args: { copyAction, exportAction } }
export const ExportInProgress: Story = {
    args: { copyAction, exportAction: { ...exportAction, loading: true } },
    // The busy button's spinner is the state this story shows, so the snapshot must not wait for it to go.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
const search = {
    query: 'seats',
    status: 'ready' as const,
    total: 3,
    matchingSteps: 2,
    position: 1,
    failure: null,
    onQueryChange: () => {},
    onStep: () => {},
}

// Stand-ins for the review controls the view passes in, at the widths the trace drawer and page give the header.
const reviewActions = (
    <>
        <LemonButton type="secondary" size="small">
            Review
        </LemonButton>
        <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
            Add to queue
        </LemonButton>
    </>
)
const fullHeader = { search, copyAction, exportAction, actions: reviewActions }

export const OneRow: Story = { args: fullHeader }
export const ToolbarBelowTitle: Story = { args: fullHeader, decorators: [withWidth(673)] }
export const ButtonsBelowSearch: Story = {
    args: { ...fullHeader, name: 'support-agent.handle-inbound-ticket.classify-and-route', hasError: true },
    decorators: [withWidth(448)],
}
export const WithSearch: Story = { args: { search } }
export const Narrow: Story = {
    args: { name: 'a-very-long-trace-name-that-should-truncate-cleanly', copyAction, exportAction },
    decorators: [withWidth(360)],
}
