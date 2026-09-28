import type { Meta, StoryObj } from '@storybook/react'

import { EvaluationResultTag } from './EvaluationResultTag'

const meta: Meta<typeof EvaluationResultTag> = {
    title: 'Scenes-App/LLM observability/EvaluationResultTag',
    component: EvaluationResultTag,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof EvaluationResultTag>

export const Numeric: Story = {
    render: () => (
        <div className="flex flex-wrap gap-6">
            <div className="space-y-2">
                <div>Large score</div>
                <EvaluationResultTag
                    run={{ status: 'completed', result: null, result_type: 'numeric', score: 123456789 }}
                />
            </div>
            <div className="space-y-2">
                <div>Fractional score</div>
                <EvaluationResultTag
                    run={{ status: 'completed', result: null, result_type: 'numeric', score: 1 / 3 }}
                />
            </div>
            <div className="space-y-2">
                <div>Score without a passing rule</div>
                <EvaluationResultTag run={{ status: 'completed', result: null, result_type: 'numeric', score: 0 }} />
            </div>
            <div className="space-y-2">
                <div>Pass at or above 7</div>
                <EvaluationResultTag
                    run={{ status: 'completed', result: null, result_type: 'numeric', score: 7 }}
                    passingRule={{ operator: 'gte', threshold: 7 }}
                />
            </div>
            <div className="space-y-2">
                <div>Below the passing threshold</div>
                <EvaluationResultTag
                    run={{ status: 'completed', result: null, result_type: 'numeric', score: 6.5 }}
                    passingRule={{ operator: 'gte', threshold: 7 }}
                />
            </div>
            <div className="space-y-2">
                <div>Not applicable</div>
                <EvaluationResultTag
                    run={{ status: 'completed', result: null, result_type: 'numeric', applicable: false }}
                />
            </div>
            <div className="space-y-2">
                <div>Skipped before scoring</div>
                <EvaluationResultTag
                    run={{ status: 'completed', result: null, result_type: 'numeric', skipped: true }}
                />
            </div>
            <div className="space-y-2">
                <div>Evaluation error</div>
                <EvaluationResultTag run={{ status: 'failed', result: null, result_type: 'numeric' }} />
            </div>
        </div>
    ),
}
