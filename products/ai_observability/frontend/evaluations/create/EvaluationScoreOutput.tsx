import { useState } from 'react'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import type { EvaluationOutputConfig } from '../types'

/** The score a run needs to pass. Without a passing score, scores carry no pass or fail. */
export function EvaluationScoreOutput({
    config,
    onChange,
}: {
    config: EvaluationOutputConfig
    onChange: (patch: EvaluationOutputConfig) => void
}): JSX.Element {
    const rule = config.passing_rule && 'threshold' in config.passing_rule ? config.passing_rule : null
    // The direction is kept here until a passing score exists, because a rule needs both.
    const [pendingOperator, setPendingOperator] = useState<'gte' | 'lte'>('gte')
    const operator = rule?.operator ?? pendingOperator
    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>A run passes when the score is</span>
                <LemonSelect
                    size="small"
                    value={operator}
                    options={[
                        { value: 'gte', label: 'at least' },
                        { value: 'lte', label: 'at most' },
                    ]}
                    onChange={(next) => {
                        setPendingOperator(next)
                        if (rule) {
                            onChange({ passing_rule: { ...rule, operator: next } })
                        }
                    }}
                />
                <LemonInput
                    type="number"
                    size="small"
                    className="w-20"
                    value={rule && Number.isFinite(rule.threshold) ? rule.threshold : undefined}
                    onChange={(threshold) =>
                        onChange({
                            passing_rule:
                                threshold == null || !Number.isFinite(threshold) ? null : { operator, threshold },
                        })
                    }
                    placeholder="score"
                    aria-label="Passing score"
                    data-attr="llma-evaluation-numeric-threshold"
                />
            </div>
            <span className="text-xs text-secondary">
                Leave the passing score empty to keep scores without a pass or fail. Pass rates and reports need one.
            </span>
        </div>
    )
}
