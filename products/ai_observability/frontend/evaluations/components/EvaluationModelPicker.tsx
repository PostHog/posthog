import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ByokModelPickerNotice } from '../../ByokModelPickerNotice'
import { getModelPickerFooterLink, ModelPicker } from '../../ModelPicker'
import { modelPickerLogic } from '../../modelPickerLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { JudgeMethod } from '../types'

export function EvaluationModelPicker(): JSX.Element {
    const { byokModels, byokModelsLoading, providerKeysLoading } = useValues(modelPickerLogic)
    const {
        selectedModel,
        selectedPickerProviderKeyId,
        modelSelectionRequired,
        evaluation,
        usesDecisionModel,
        judgeMethod,
        judgeModelGroups: groups,
    } = useValues(llmEvaluationLogic)
    const { selectModelFromPicker, setJudgeMethod } = useActions(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Evals always run on the team's own provider key, so only BYOK models are offered.
    const selectedModelName = byokModels.find(
        (m) => m.id === selectedModel && m.providerKeyId === selectedPickerProviderKeyId
    )?.name
    const loading = byokModelsLoading || providerKeysLoading

    const footerLink = getModelPickerFooterLink(groups.some((group) => !group.disabledReason))

    return (
        <div className="bg-bg-light border rounded p-6">
            <h3 className="text-lg font-semibold mb-2">Judge model</h3>
            <p className="text-muted text-sm mb-4">
                Choose how to judge responses, then select a model from your configured AI providers.
            </p>

            <div className="space-y-4">
                <LemonField.Pure label="Judge method">
                    <LemonSegmentedButton<JudgeMethod>
                        value={judgeMethod}
                        onChange={setJudgeMethod}
                        disabledReason={loading ? 'Loading model capabilities.' : undefined}
                        options={[
                            { value: 'llm', label: 'LLM with explanation' },
                            {
                                value: 'decision',
                                label: 'Decision model',
                                disabledReason: !featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SYSTEM_ONE_EVALUATIONS]
                                    ? 'Decision model evaluations are not enabled for this project.'
                                    : undefined,
                            },
                        ]}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Model">
                    <div>
                        <ModelPicker
                            model={selectedModel}
                            selectedProviderKeyId={selectedPickerProviderKeyId}
                            onSelect={selectModelFromPicker}
                            groups={groups}
                            loading={loading}
                            footerLink={footerLink}
                            selectedModelName={selectedModelName}
                            data-attr="evaluation-model-selector"
                        />
                        <ByokModelPickerNotice forEvaluation />
                        {usesDecisionModel && !loading && !groups.some((group) => group.models.length > 0) && (
                            <p className="text-sm text-muted mt-2">
                                No decision models are available. Configure an OpenRouter or custom decision provider in
                                AI provider settings.
                            </p>
                        )}
                        {evaluation && usesDecisionModel && (
                            <p className="text-sm text-muted mt-2">
                                {evaluation.output_type === 'categorical'
                                    ? 'This decision model selects categories without written reasoning. For multiple selections, each category is included when its probability is 50% or higher.'
                                    : evaluation.output_type === 'numeric'
                                      ? 'This decision model estimates a score between your minimum and maximum without written reasoning. Define what low and high scores mean in your evaluation prompt. Scores can be fractional.'
                                      : 'This decision model returns a probability without written reasoning. A probability of 50% or higher produces a true result.'}
                            </p>
                        )}
                        {modelSelectionRequired && !selectedModel && (
                            <p className="text-sm text-danger mt-1">Select a judge model.</p>
                        )}
                    </div>
                </LemonField.Pure>
            </div>
        </div>
    )
}
