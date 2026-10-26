import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { EvaluationSettleConfig } from '../components/EvaluationSettleConfig'
import { EvaluationTriggersPanel } from '../components/EvaluationTriggersPanel'
import { evaluationOffersSessionTarget } from '../evaluationCapabilities'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationTarget } from '../types'
import { CreateStep, type StepProgress } from './CreateStep'
import { scopeText } from './evaluationSummary'
import { EvaluationVolumeEstimate } from './EvaluationVolumeEstimate'

const TARGET_HINTS: Record<EvaluationTarget, string> = {
    generation: 'Runs on each matching generation as soon as it arrives.',
    trace: 'Runs once per trace, after the trace has had time to finish. Only generations sent with a trace ID count.',
    session:
        'Runs once per session, after the session has had time to finish. Only generations sent with a session ID count.',
}

/** Step three: the live traffic the evaluation runs on, and how much of it. */
export function EvaluationTargetStep(progress: StepProgress): JSX.Element | null {
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
        <CreateStep
            number={3}
            title="Choose what it runs on"
            description="Pick the live traffic it checks, and how much of it. Check the estimate before you start it."
            summary={scopeText(evaluation)}
            {...progress}
        >
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
            <div className="flex flex-col gap-2">
                <h4 className="mb-0 text-base font-semibold">Triggers</h4>
                <EvaluationTriggersPanel />
            </div>
            <EvaluationVolumeEstimate />
        </CreateStep>
    )
}
