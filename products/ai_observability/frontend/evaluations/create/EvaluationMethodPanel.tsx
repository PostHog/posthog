import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { EvaluationJudgeModelPicker } from '../components/EvaluationJudgeModelPicker'
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
    const { evaluation, usesDecisionModel } = useValues(llmEvaluationLogic)
    const { setEvaluationType, setJudgeMethod } = useActions(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!evaluation) {
        return null
    }
    const type = evaluation.evaluation_type
    const method: Method = type === 'llm_judge' && usesDecisionModel ? 'decision' : type
    const isJudge = type === 'llm_judge'
    const setMethod = (next: Method): void => {
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
            {/* Top-aligned, so notices under the model picker do not push the method buttons down. */}
            <div className="flex flex-wrap items-start gap-2 text-sm">
                <LemonSegmentedButton
                    value={method}
                    onChange={setMethod}
                    options={[
                        { value: 'llm_judge', label: 'LLM judge' },
                        ...(featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SYSTEM_ONE_EVALUATIONS]
                            ? [{ value: 'decision' as const, label: 'Decision model' }]
                            : []),
                        { value: 'hog', label: 'Code' },
                        { value: 'sentiment', label: 'Sentiment' },
                    ]}
                    data-attr="llma-evaluation-create-method"
                />
                {isJudge && (
                    <>
                        <span className="font-semibold h-10 flex items-center">with</span>
                        <div className="w-72 max-w-full">
                            <EvaluationJudgeModelPicker />
                        </div>
                    </>
                )}
            </div>
            <p className="mb-0 text-sm text-secondary">{METHOD_HINTS[method]}</p>
        </div>
    )
}
