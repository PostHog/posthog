import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ByokModelPickerNotice } from '../../ByokModelPickerNotice'
import { getModelPickerFooterLink, ModelPicker } from '../../ModelPicker'
import { modelPickerLogic } from '../../modelPickerLogic'
import { booleanOutputConfigError } from '../constants'
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
    const { selectModelFromPicker, setJudgeMethod, patchOutputConfig } = useActions(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Evals always run on the team's own provider key, so only BYOK models are offered.
    const selectedModelName = byokModels.find(
        (m) => m.id === selectedModel && m.providerKeyId === selectedPickerProviderKeyId
    )?.name
    const loading = byokModelsLoading || providerKeysLoading

    const footerLink = getModelPickerFooterLink(groups.some((group) => !group.disabledReason))

    return (
        <div className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6">
            <h3 className="text-lg font-semibold mb-2">Judge model</h3>
            <p className="text-muted text-sm mb-4">
                Choose how to judge responses, then select a model from your configured AI providers.
            </p>

            <div className="@container/judge-model space-y-4">
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
                                No decision models are available from your configured AI providers.
                            </p>
                        )}
                        {evaluation && usesDecisionModel && (
                            <p className="text-sm text-muted mt-2">
                                {evaluation.output_type === 'categorical'
                                    ? 'This decision model selects categories without written reasoning. For multiple selections, each category is included when its probability is 50% or higher.'
                                    : evaluation.output_type === 'numeric'
                                      ? 'This decision model estimates a score between your minimum and maximum without written reasoning. Define what low and high scores mean in your evaluation prompt. Scores can be fractional.'
                                      : 'This decision model returns a probability without written reasoning. The decision threshold determines whether the result is true.'}
                            </p>
                        )}
                        {modelSelectionRequired && !selectedModel && (
                            <p className="text-sm text-danger mt-1">Select a judge model.</p>
                        )}
                    </div>
                </LemonField.Pure>
                {evaluation?.evaluation_type === 'llm_judge' &&
                    evaluation.output_type === 'boolean' &&
                    usesDecisionModel && (
                        <LemonField.Pure
                            label="Decision threshold"
                            htmlFor="llma-evaluation-decision-threshold"
                            error={booleanOutputConfigError(evaluation.output_config)}
                        >
                            <LemonInput
                                id="llma-evaluation-decision-threshold"
                                type="number"
                                value={Number(
                                    ((evaluation.output_config.decision_threshold ?? 0.5) * 100).toPrecision(15)
                                )}
                                onChange={(percentage) =>
                                    patchOutputConfig({
                                        decision_threshold: percentage == null ? NaN : percentage / 100,
                                    })
                                }
                                min={0}
                                max={100}
                                step="any"
                                suffix={<span>%</span>}
                                data-attr="llma-evaluation-decision-threshold"
                            />
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
