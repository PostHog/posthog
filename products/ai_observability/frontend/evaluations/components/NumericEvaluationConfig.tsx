import { useId } from 'react'

import { LemonBanner, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { numericOutputConfigError } from '../constants'
import type { EvaluationOutputConfig } from '../types'

export function NumericEvaluationConfig({
    config,
    onChange,
}: {
    config: EvaluationOutputConfig
    onChange: (patch: EvaluationOutputConfig) => void
}): JSX.Element {
    const id = useId()
    const rule = config.passing_rule
    const error = numericOutputConfigError(config)
    return (
        <div className="space-y-4">
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            <div className="flex flex-wrap gap-4">
                {(['min', 'max', 'step'] as const).map((field) => (
                    <LemonField.Pure
                        key={field}
                        htmlFor={`${id}-${field}`}
                        label={{ min: 'Minimum (optional)', max: 'Maximum (optional)', step: 'Step (optional)' }[field]}
                    >
                        <LemonInput
                            id={`${id}-${field}`}
                            type="number"
                            value={config[field] ?? NaN}
                            onChange={(value) => onChange({ [field]: Number.isFinite(value) ? value : null })}
                            placeholder="Not set"
                            data-attr={`llma-evaluation-numeric-${field}`}
                        />
                    </LemonField.Pure>
                ))}
            </div>
            <p className="text-muted text-sm">Bounds are inclusive. Step guides scoring without rounding results.</p>
            <LemonSwitch
                label="Allow N/A responses"
                checked={config.allows_na ?? false}
                onChange={(allows_na) => onChange({ allows_na })}
                data-attr="llma-evaluation-numeric-allows-na"
            />
            <LemonSwitch
                label="Set a passing rule"
                checked={!!rule}
                onChange={(enabled) =>
                    onChange({
                        passing_rule: enabled ? { operator: 'gte', threshold: config.min ?? config.max ?? 0 } : null,
                    })
                }
                data-attr="llma-evaluation-numeric-passing-rule"
            />
            {rule ? (
                <div className="flex flex-wrap items-end gap-4">
                    <LemonField.Pure label="Pass when score is" htmlFor={`${id}-operator`}>
                        <LemonSelect
                            id={`${id}-operator`}
                            value={rule.operator}
                            options={[
                                { value: 'gte', label: 'At least (≥)' },
                                { value: 'lte', label: 'At most (≤)' },
                            ]}
                            onChange={(operator) => onChange({ passing_rule: { ...rule, operator } })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Threshold" htmlFor={`${id}-threshold`}>
                        <LemonInput
                            id={`${id}-threshold`}
                            type="number"
                            value={rule.threshold}
                            onChange={(threshold) =>
                                onChange({
                                    passing_rule: { ...rule, threshold: threshold ?? NaN },
                                })
                            }
                            min={config.min ?? undefined}
                            max={config.max ?? undefined}
                            step={config.step ?? 'any'}
                            data-attr="llma-evaluation-numeric-threshold"
                        />
                    </LemonField.Pure>
                    <p className="text-muted text-sm">
                        Changing this rule also updates how historical scores count as passes.
                    </p>
                </div>
            ) : (
                <p className="text-muted text-sm">
                    Scores stay neutral without a passing rule. Add a rule to enable pass rates and reports.
                </p>
            )}
        </div>
    )
}
