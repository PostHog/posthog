import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** The probability, as a percentage, at which a decision model answers true. */
export function DecisionThresholdInput({ id }: { id?: string }): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { patchOutputConfig } = useActions(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    return (
        <LemonInput
            id={id}
            type="number"
            className="w-24"
            value={Number(((evaluation.output_config.decision_threshold ?? 0.5) * 100).toPrecision(15))}
            onChange={(percentage) =>
                patchOutputConfig({ decision_threshold: percentage == null ? NaN : percentage / 100 })
            }
            min={0}
            max={100}
            step="any"
            suffix={<span>%</span>}
            aria-label="Decision threshold"
            data-attr="llma-evaluation-decision-threshold"
        />
    )
}
