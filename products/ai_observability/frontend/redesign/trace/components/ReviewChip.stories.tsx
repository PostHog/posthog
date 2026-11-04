import type { Meta, StoryObj } from '@storybook/react'

import type { TraceHumanReviewApi } from '../../../generated/api.schemas'
import { withWidth } from '../storyFixtures'
import { ReviewChip } from './ReviewChip'

const REVIEW: TraceHumanReviewApi = {
    reviewedBy: 'Ada',
    reviewedAt: '2026-09-01T10:20:00Z',
    comment: 'The refund policy is quoted correctly, but the answer is long.',
    scores: [
        { name: 'Accuracy', value: 'Good', label: 'Accuracy: Good' },
        { name: 'Tone', value: '4.5', label: 'Tone: 4.5' },
    ],
}

const meta: Meta<typeof ReviewChip> = {
    title: 'Scenes-App/AI observability/Trace view/Review chip',
    component: ReviewChip,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { status: { review: REVIEW, queue: null }, queueHref: null },
}
export default meta

type Story = StoryObj<typeof ReviewChip>

export const Reviewed: Story = {}
export const ReviewedWithoutScores: Story = {
    args: { status: { review: { ...REVIEW, scores: [], comment: null }, queue: null } },
}
export const Queued: Story = {
    args: {
        status: { review: null, queue: { id: 'q1', name: 'Support QA', itemId: 'i1' } },
        queueHref: '/ai-observability/reviews?queue_id=q1',
        onRemoveFromQueue: () => {},
    },
}
export const LongQueueNameNarrow: Story = {
    args: {
        status: {
            review: null,
            queue: { id: 'q1', name: 'Refund and billing escalations from the enterprise tier', itemId: 'i1' },
        },
        queueHref: '/ai-observability/reviews?queue_id=q1',
    },
    decorators: [withWidth(240)],
}
