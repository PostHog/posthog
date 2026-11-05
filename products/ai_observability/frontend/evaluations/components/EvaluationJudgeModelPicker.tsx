import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ByokModelPickerNotice } from '../../ByokModelPickerNotice'
import { getModelPickerFooterActions, ModelPicker } from '../../ModelPicker'
import { modelPickerLogic } from '../../modelPickerLogic'
import { AddKeyModal } from '../../settings/AddKeyModal'
import { llmProviderKeysLogic } from '../../settings/llmProviderKeysLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationReasoningLevelButton } from './EvaluationReasoningLevelButton'

/** The judge model picker with its notices, for the models the current judge method can use. */
export function EvaluationJudgeModelPicker(): JSX.Element {
    const { byokModelsLoading, providerKeysLoading, evaluationModelNotice } = useValues(modelPickerLogic)
    const {
        selectedModel,
        selectedModelName,
        selectedPickerProviderKeyId,
        usesDecisionModel,
        judgeModelGroups,
        selectedModelSupportsReasoning,
    } = useValues(llmEvaluationLogic)
    const { selectModelFromPicker } = useActions(llmEvaluationLogic)
    const { setNewKeyModalOpen } = useActions(llmProviderKeysLogic)

    const loading = byokModelsLoading || providerKeysLoading

    return (
        <div>
            <div className="flex gap-2">
                <div className="flex-1 min-w-0">
                    {evaluationModelNotice?.kind === 'no-keys' ? (
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            fullWidth
                            center
                            onClick={() => setNewKeyModalOpen(true)}
                            data-attr="evaluation-add-api-key"
                        >
                            Add API key
                        </LemonButton>
                    ) : (
                        <ModelPicker
                            model={selectedModel}
                            selectedProviderKeyId={selectedPickerProviderKeyId}
                            onSelect={selectModelFromPicker}
                            groups={judgeModelGroups}
                            loading={loading}
                            footerActions={getModelPickerFooterActions(
                                judgeModelGroups.some((group) => !group.disabledReason),
                                () => setNewKeyModalOpen(true)
                            )}
                            selectedModelName={selectedModelName}
                            data-attr="evaluation-model-selector"
                        />
                    )}
                </div>
                {selectedModelSupportsReasoning && <EvaluationReasoningLevelButton />}
            </div>
            <ByokModelPickerNotice forEvaluation />
            <AddKeyModal />
            {usesDecisionModel && !loading && !judgeModelGroups.some((group) => group.models.length > 0) && (
                <p className="text-sm text-muted mt-2">
                    No decision models are available from your configured AI providers.
                </p>
            )}
        </div>
    )
}
