import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { EvaluationJudgeModelPicker } from '../components/EvaluationJudgeModelPicker'
import { decisionModelHint } from '../constants'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** The model a judge or decision model runs on, from the team's AI providers, with what that model does. */
export function EvaluationModelPanel(): JSX.Element | null {
    const { evaluation, usesDecisionModel, includeMedia } = useValues(llmEvaluationLogic)
    const { setIncludeMedia } = useActions(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!evaluation) {
        return null
    }
    return (
        <div className="flex flex-col gap-4">
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
            {featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_JUDGE_IMAGES] && !usesDecisionModel && (
                <LemonField.Pure label="Attachments">
                    <LemonSwitch
                        checked={includeMedia}
                        onChange={setIncludeMedia}
                        bordered
                        label="Send to the judge"
                        data-attr="llma-evaluation-include-attachments"
                    />
                    <p className="text-muted text-sm">
                        The judge sees the images, PDFs and audio in what it evaluates. PDFs need an OpenAI, Anthropic
                        or Gemini judge, and audio a Gemini judge or an OpenAI audio model. Other file types are not
                        supported yet.
                    </p>
                </LemonField.Pure>
            )}
        </div>
    )
}
