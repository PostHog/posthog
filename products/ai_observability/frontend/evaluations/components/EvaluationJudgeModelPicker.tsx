import { useActions, useValues } from 'kea'

import { ByokModelPickerNotice } from '../../ByokModelPickerNotice'
import { getModelPickerFooterLink, ModelPicker } from '../../ModelPicker'
import { modelPickerLogic } from '../../modelPickerLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationReasoningLevelButton } from './EvaluationReasoningLevelButton'

/** The judge model picker with its notices, for the models the current judge method can use. */
export function EvaluationJudgeModelPicker(): JSX.Element {
    const { byokModelsLoading, providerKeysLoading } = useValues(modelPickerLogic)
    const {
        selectedModel,
        selectedModelName,
        selectedPickerProviderKeyId,
        usesDecisionModel,
        judgeModelGroups,
        selectedModelSupportsReasoning,
    } = useValues(llmEvaluationLogic)
    const { selectModelFromPicker } = useActions(llmEvaluationLogic)

    const loading = byokModelsLoading || providerKeysLoading

    return (
        <div>
            <div className="flex gap-2">
                <div className="flex-1 min-w-0">
                    <ModelPicker
                        model={selectedModel}
                        selectedProviderKeyId={selectedPickerProviderKeyId}
                        onSelect={selectModelFromPicker}
                        groups={judgeModelGroups}
                        loading={loading}
                        footerLink={getModelPickerFooterLink(judgeModelGroups.some((group) => !group.disabledReason))}
                        selectedModelName={selectedModelName}
                        data-attr="evaluation-model-selector"
                    />
                </div>
                {selectedModelSupportsReasoning && <EvaluationReasoningLevelButton />}
            </div>
            <ByokModelPickerNotice forEvaluation />
            {usesDecisionModel && !loading && !judgeModelGroups.some((group) => group.models.length > 0) && (
                <p className="text-sm text-muted mt-2">
                    No decision models are available from your configured AI providers.
                </p>
            )}
        </div>
    )
}
