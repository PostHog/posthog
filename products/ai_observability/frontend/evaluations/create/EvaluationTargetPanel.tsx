import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { EvaluationSettleConfig } from '../components/EvaluationSettleConfig'
import { evaluationOffersSessionTarget } from '../evaluationCapabilities'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationTarget } from '../types'

const TARGET_HINTS: Record<EvaluationTarget, string> = {
    generation: 'Runs on each matching generation as soon as it arrives.',
    trace: 'Runs once per trace, after the trace has had time to finish. Only generations sent with a trace ID count.',
    session:
        'Runs once per session, after the session has had time to finish. Only generations sent with a session ID and a trace ID count.',
}

/** What one run covers, and how long a trace or session gets to finish first. */
export function EvaluationTargetPanel(): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationTarget } = useActions(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!evaluation) {
        return null
    }
    const isSentiment = evaluation.evaluation_type === 'sentiment'
    const target: EvaluationTarget = isSentiment ? 'generation' : evaluation.target
    const offersSession = evaluationOffersSessionTarget(
        evaluation,
        !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVAL_SETTLING_STRATEGY]
    )

    return (
        <div className="flex flex-col gap-4">
            {!isSentiment && (
                <LemonField.Pure label="Evaluate" help={TARGET_HINTS[target]}>
                    <LemonSegmentedButton
                        value={target}
                        onChange={setEvaluationTarget}
                        options={[
                            { value: 'generation', label: 'Each generation' },
                            { value: 'trace', label: 'Whole trace' },
                            ...(offersSession ? [{ value: 'session' as const, label: 'Whole session' }] : []),
                        ]}
                        fullWidth
                        data-attr="llma-evaluation-create-target"
                    />
                </LemonField.Pure>
            )}
            <EvaluationSettleConfig />
        </div>
    )
}
