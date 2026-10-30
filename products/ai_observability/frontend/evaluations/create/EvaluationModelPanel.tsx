import { useValues } from 'kea'

import { EvaluationJudgeModelPicker } from '../components/EvaluationJudgeModelPicker'
import { decisionModelHint } from '../constants'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** The model a judge or decision model runs on, from the team's AI providers, with what that model does. */
export function EvaluationModelPanel(): JSX.Element | null {
    const { evaluation, usesDecisionModel } = useValues(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    return (
        <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
            <div className="w-80 max-w-full">
                <EvaluationJudgeModelPicker />
            </div>
            <p className="mb-0 flex-1 basis-64 text-sm text-secondary">
                {usesDecisionModel
                    ? decisionModelHint(evaluation.output_type)
                    : 'Runs on your own AI provider key. Each run is one call to this model.'}
            </p>
        </div>
    )
}
