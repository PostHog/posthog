import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { modelPickerLogic } from '../../modelPickerLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

type Method = 'llm_judge' | 'decision' | 'hog' | 'sentiment'

const METHOD_HINTS: Record<Method, React.ReactNode> = {
    llm_judge: 'An LLM grades each run against your prompt and explains why, using your own AI provider key.',
    decision:
        'A decision model answers your prompt with a probability and no written reasoning. It is faster and cheaper than an LLM judge.',
    hog: (
        <>
            Deterministic{' '}
            <Link to="https://posthog.com/docs/hog" target="_blank">
                Hog code
            </Link>{' '}
            returns the result. It makes no LLM calls, and you can test it on recent generations.
        </>
    ),
    sentiment:
        "Classifies the user's last message as positive, neutral, or negative. Works for English only, so use an LLM judge for other languages.",
}

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
            <div>
                <LemonSegmentedButton
                    value={method}
                    onChange={setMethod}
                    options={[
                        { value: 'llm_judge', label: 'LLM judge', disabledReason: judgeDisabledReason },
                        { value: 'decision', label: 'Decision model', disabledReason: judgeDisabledReason },
                        { value: 'hog', label: 'Code' },
                        {
                            value: 'sentiment',
                            label: 'Sentiment',
                            disabledReason:
                                !isNewEvaluation && ['numeric', 'categorical'].includes(evaluation.output_type)
                                    ? 'Create a new evaluation to change what it returns.'
                                    : undefined,
                        },
                    ]}
                    data-attr="llma-evaluation-create-method"
                />
            </div>
            <p className="mb-0 text-sm text-secondary">{METHOD_HINTS[method]}</p>
        </div>
    )
}
