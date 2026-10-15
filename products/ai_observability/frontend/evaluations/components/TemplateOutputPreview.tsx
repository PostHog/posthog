import { IconCheck, IconX } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { EvaluationTemplate } from '../templates'

const MAX_CATEGORIES = 2
const MAX_SCALE_STEPS = 10

function NumericPreview({ template }: { template: EvaluationTemplate }): JSX.Element {
    const { min, max, step, passing_rule } = template.output_config
    const threshold = passing_rule && 'threshold' in passing_rule ? passing_rule : null
    const passes = (value: number): boolean =>
        !threshold || (threshold.operator === 'gte' ? value >= threshold.threshold : value <= threshold.threshold)

    if (min != null && max != null && step && (max - min) / step < MAX_SCALE_STEPS) {
        const values = Array.from({ length: Math.round((max - min) / step) + 1 }, (_, i) => min + i * step)
        return (
            <>
                {values.map((value) => (
                    <LemonTag key={value} type={passes(value) ? 'success' : 'muted'} size="small">
                        {value}
                    </LemonTag>
                ))}
            </>
        )
    }
    return (
        <LemonTag type="muted" size="small">
            {threshold
                ? `Number, passes at ${threshold.threshold} or ${threshold.operator === 'gte' ? 'more' : 'less'}`
                : 'Number'}
        </LemonTag>
    )
}

function CategoricalPreview({ template }: { template: EvaluationTemplate }): JSX.Element {
    const { options = [], passing_rule } = template.output_config
    const passing = passing_rule && 'categories' in passing_rule ? passing_rule.categories : []
    return (
        <>
            {options.slice(0, MAX_CATEGORIES).map((option) => (
                <LemonTag key={option.key} type={passing.includes(option.key) ? 'success' : 'muted'} size="small">
                    {option.label}
                </LemonTag>
            ))}
            {options.length > MAX_CATEGORIES && (
                <span className="text-xs text-secondary">{`+${options.length - MAX_CATEGORIES}`}</span>
            )}
        </>
    )
}

/** What a run of this template returns, so the card shows the output before anyone opens it. */
export function TemplateOutputPreview({ template }: { template: EvaluationTemplate }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1">
            {template.output_type === 'numeric' ? (
                <NumericPreview template={template} />
            ) : template.output_type === 'categorical' ? (
                <CategoricalPreview template={template} />
            ) : template.output_type === 'sentiment' ? (
                <>
                    <LemonTag type="success" size="small">
                        Positive
                    </LemonTag>
                    <LemonTag type="muted" size="small">
                        Neutral
                    </LemonTag>
                    <LemonTag type="danger" size="small">
                        Negative
                    </LemonTag>
                </>
            ) : (
                <>
                    <LemonTag type="success" size="small" icon={<IconCheck />}>
                        Pass
                    </LemonTag>
                    <LemonTag type="danger" size="small" icon={<IconX />}>
                        Fail
                    </LemonTag>
                </>
            )}
        </div>
    )
}
