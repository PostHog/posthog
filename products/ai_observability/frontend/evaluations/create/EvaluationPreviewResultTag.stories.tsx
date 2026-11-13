import type { Meta, StoryObj } from '@storybook/react'

import { EvaluationPreviewResultTag } from './EvaluationPreviewResultTag'

const meta: Meta<typeof EvaluationPreviewResultTag> = {
    title: 'Scenes-App/AI observability/New evaluation/Preview result tag',
    component: EvaluationPreviewResultTag,
    parameters: { layout: 'padded', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof EvaluationPreviewResultTag>

export const Outcomes: Story = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <EvaluationPreviewResultTag result={{ outcome: 'pass', value: 'True', detail: 'Names the reset link.' }} />
            <EvaluationPreviewResultTag result={{ outcome: 'fail', value: 'False', detail: null }} />
            <EvaluationPreviewResultTag result={{ outcome: 'na', value: 'N/A', detail: null }} />
            <EvaluationPreviewResultTag result={{ outcome: 'error', value: 'N/A', detail: 'Timed out' }} />
            <EvaluationPreviewResultTag result={{ outcome: null, value: '4.2', detail: null }} />
            <EvaluationPreviewResultTag result={{ outcome: null, value: 'Billing, Refund', detail: null }} />
        </div>
    ),
}
