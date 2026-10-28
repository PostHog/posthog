import { useActions, useValues } from 'kea'

import { ByokModelPickerNotice } from '../../ByokModelPickerNotice'
import { getModelPickerFooterLink, ModelPicker } from '../../ModelPicker'
import { modelPickerLogic } from '../../modelPickerLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** The judge model picker with its notices, for the models the current judge method can use. */
export function EvaluationJudgeModelPicker(): JSX.Element {
    const { byokModelsLoading, providerKeysLoading } = useValues(modelPickerLogic)
    const { selectedModel, selectedModelName, selectedPickerProviderKeyId, usesDecisionModel, judgeModelGroups } =
        useValues(llmEvaluationLogic)
    const { selectModelFromPicker } = useActions(llmEvaluationLogic)

    const loading = byokModelsLoading || providerKeysLoading

    return (
        <div>
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
            <ByokModelPickerNotice forEvaluation />
            {usesDecisionModel && !loading && !judgeModelGroups.some((group) => group.models.length > 0) && (
                <p className="text-sm text-muted mt-2">
                    No decision models are available from your configured AI providers.
                </p>
            )}
        </div>
    )
}
