import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { modelPickerLogic } from '../../modelPickerLogic'
import { booleanOutputConfigError, decisionModelHint } from '../constants'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { JudgeMethod } from '../types'
import { DecisionThresholdInput } from './DecisionThresholdInput'
import { EvaluationJudgeModelPicker } from './EvaluationJudgeModelPicker'

export function EvaluationModelPicker(): JSX.Element {
    const { byokModelsLoading, providerKeysLoading } = useValues(modelPickerLogic)
    const { evaluation, usesDecisionModel, judgeMethod, includeMedia } = useValues(llmEvaluationLogic)
    const { setJudgeMethod, setIncludeMedia } = useActions(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const loading = byokModelsLoading || providerKeysLoading

    return (
        <div className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6">
            <div className="@container/judge-model space-y-4">
                <div>
                    <h3 className="text-lg font-semibold mb-2">Judge model</h3>
                    <p className="text-muted text-sm mb-0">
                        Choose how to judge responses, then select a model from your configured AI providers.
                    </p>
                </div>
                <LemonField.Pure label="Judge method">
                    <LemonSegmentedButton<JudgeMethod>
                        value={judgeMethod}
                        onChange={setJudgeMethod}
                        className="max-w-full"
                        disabledReason={loading ? 'Loading model capabilities.' : undefined}
                        options={[
                            {
                                value: 'llm',
                                label: (
                                    <span className="whitespace-normal @min-[24rem]/judge-model:whitespace-nowrap">
                                        LLM with explanation
                                    </span>
                                ),
                            },
                            {
                                value: 'decision',
                                label: (
                                    <span className="whitespace-normal @min-[24rem]/judge-model:whitespace-nowrap">
                                        Decision model
                                    </span>
                                ),
                            },
                        ]}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Model">
                    <div>
                        <EvaluationJudgeModelPicker />
                        {evaluation && usesDecisionModel && (
                            <p className="text-sm text-muted mt-2">{decisionModelHint(evaluation.output_type)}</p>
                        )}
                    </div>
                </LemonField.Pure>
                {featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_JUDGE_IMAGES] &&
                    evaluation?.evaluation_type === 'llm_judge' &&
                    !usesDecisionModel && (
                        <LemonField.Pure label="Attachments">
                            <LemonSwitch
                                checked={includeMedia}
                                onChange={setIncludeMedia}
                                bordered
                                label="Send to the judge"
                                data-attr="llma-evaluation-include-attachments"
                            />
                            <p className="text-muted text-sm">
                                The judge sees the images in what it evaluates, and PDFs when it runs on OpenAI,
                                Anthropic or Gemini. Other file types are not supported yet.
                            </p>
                        </LemonField.Pure>
                    )}
                {evaluation?.evaluation_type === 'llm_judge' &&
                    evaluation.output_type === 'boolean' &&
                    usesDecisionModel && (
                        <LemonField.Pure
                            label="Decision threshold"
                            htmlFor="llma-evaluation-decision-threshold"
                            error={booleanOutputConfigError(evaluation.output_config)}
                        >
                            <DecisionThresholdInput id="llma-evaluation-decision-threshold" />
                            <p className="text-muted text-sm">
                                A probability at or above this threshold produces a true result. Applies to new runs;
                                past results stay unchanged.
                            </p>
                        </LemonField.Pure>
                    )}
            </div>
        </div>
    )
}
