import type { Meta, StoryObj } from '@storybook/react'

import type { TraceHumanReviewApi, TraceReviewQueueAssignmentApi } from '../../../generated/api.schemas'
import { TraceReviewCell } from './TraceReviewCell'

const REVIEW: TraceHumanReviewApi = {
    reviewedBy: 'Ana',
    reviewedAt: '2026-09-01T12:00:00Z',
    comment: null,
    scores: [],
}
const QUEUE: TraceReviewQueueAssignmentApi = { id: 'queue-1', name: 'Billing answers', itemId: 'item-1' }

const meta: Meta<typeof TraceReviewCell> = {
    title: 'Scenes-App/AI observability/Traces/Trace review cell',
    component: TraceReviewCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { review: { review: REVIEW, queue: null } },
}
export default meta

type Story = StoryObj<typeof TraceReviewCell>

export const Reviewed: Story = {}

export const InQueue: Story = { args: { review: { review: null, queue: QUEUE } } }

export const NarrowContainer: Story = {
    args: { review: { review: REVIEW, queue: QUEUE } },
    decorators: [
        (StoryComponent) => (
            <div className="w-24">
                <StoryComponent />
            </div>
        ),
    ],
}
