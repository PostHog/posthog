import { useActions, useValues } from 'kea'

import { IconBolt, IconCode, IconEmoji, IconSparkles } from '@posthog/icons'

import { modelPickerLogic } from '../../modelPickerLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationChoiceCards } from './EvaluationChoiceCards'

type Method = 'llm_judge' | 'decision' | 'hog' | 'sentiment'

/** Who checks each run: an LLM judge with its model, a decision model, code, or the sentiment classifier. */
export function EvaluationMethodPanel(): JSX.Element | null {
    const { evaluation, usesDecisionModel, isNewEvaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationType, setJudgeMethod } = useActions(llmEvaluationLogic)
    const { byokModelsLoading, providerKeysLoading } = useValues(modelPickerLogic)

    if (!evaluation) {
        return null
    }
    const type = evaluation.evaluation_type
    const method: Method = type === 'llm_judge' && usesDecisionModel ? 'decision' : type
    const isJudge = type === 'llm_judge'
    // Without capabilities a saved model looks incompatible with the other judge method, and the switch would clear it.
    const judgeDisabledReason =
        isJudge && (byokModelsLoading || providerKeysLoading) ? 'Loading model capabilities.' : undefined
    const setMethod = (next: Method): void => {
        // Re-selecting a method would reset its prompt or code.
        if (next === method) {
            return
        }
        // Switching the type resets the prompt, so a move between the two judge methods keeps the type.
        if (next === 'llm_judge' || next === 'decision') {
            if (!isJudge) {
                setEvaluationType('llm_judge')
            }
            setJudgeMethod(next === 'decision' ? 'decision' : 'llm')
        } else {
            setEvaluationType(next)
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <h4 className="mb-0 text-sm font-semibold">Choose how it decides</h4>
            <EvaluationChoiceCards<Method>
                label="How it decides"
                value={method}
                onChange={setMethod}
                dataAttr="llma-evaluation-create-method"
                options={[
                    {
                        value: 'llm_judge',
                        label: 'LLM judge',
                        description: 'An AI model grades each run against your prompt and says why.',
                        icon: <IconSparkles />,
                        disabledReason: judgeDisabledReason,
                    },
                    {
                        value: 'decision',
                        label: 'Decision model',
                        description:
                            'Answers your prompt with a probability and no explanation, faster and cheaper than an LLM judge.',
                        icon: <IconBolt />,
                        disabledReason: judgeDisabledReason,
                    },
                    {
                        value: 'hog',
                        label: 'Code',
                        description: 'Your Hog code decides each result. It makes no AI calls.',
                        icon: <IconCode />,
                    },
                    {
                        value: 'sentiment',
                        label: 'Sentiment',
                        description: "Rates the user's last message as positive, neutral, or negative. English only.",
                        icon: <IconEmoji />,
                        disabledReason:
                            !isNewEvaluation && ['numeric', 'categorical'].includes(evaluation.output_type)
                                ? 'Create a new evaluation to change what it returns.'
                                : undefined,
                    },
                ]}
            />
        </div>
    )
}
