import type { EvaluationOutputConfig, EvaluationOutputType } from '../types'

export interface PreviewRun {
    value: string
    /** Null when there is no passing rule, so the run only records its value. */
    passes: boolean | null
    /** Where a score sits in its range, from 0 to 1. Only scores have one. */
    fill?: number
}

const SCORE_POSITIONS = [1, 0.75, 0.5, 0.25]
const DEFAULT_SCORE_SPAN = 4

/** The configured score range, filling a missing end so a one-sided or empty range still gives sensible examples. */
function scoreRange(config: EvaluationOutputConfig): [number, number] {
    const min = config.min ?? null
    const max = config.max ?? null
    if (min !== null && max !== null) {
        return [min, max]
    }
    if (min !== null) {
        return [min, min + DEFAULT_SCORE_SPAN]
    }
    if (max !== null) {
        return [max - DEFAULT_SCORE_SPAN, max]
    }
    return [1, 1 + DEFAULT_SCORE_SPAN]
}

/** Four made-up runs graded by the current passing rule, to show what the rule does before any real result exists. */
export function passRatePreview(outputType: EvaluationOutputType, config: EvaluationOutputConfig): PreviewRun[] {
    const rule = config.passing_rule ?? null
    if (outputType === 'boolean') {
        return [true, true, false, true].map((value) => ({
            value: String(value),
            passes: value !== !!config.true_is_failure,
        }))
    }
    if (outputType === 'numeric') {
        const [min, max] = scoreRange(config)
        // Whole-number ranges get whole-number examples. A fractional range keeps three significant digits, which
        // holds for any scale, and the clamp keeps rounding from stepping outside the range.
        const whole = Number.isInteger(min) && Number.isInteger(max)
        const threshold = rule && 'threshold' in rule ? rule : null
        return SCORE_POSITIONS.map((position) => {
            const exact = min + position * (max - min)
            const rounded = whole ? Math.round(exact) : Number(exact.toPrecision(3))
            const score = Math.min(max, Math.max(min, rounded))
            return {
                value: `${score} / ${max}`,
                fill: max > min ? (score - min) / (max - min) : 1,
                passes: threshold
                    ? threshold.operator === 'gte'
                        ? score >= threshold.threshold
                        : score <= threshold.threshold
                    : null,
            }
        })
    }
    const named = (config.options ?? []).filter((option) => option.key)
    const options = named.length > 0 ? named : [{ key: '', label: 'Category' }]
    const categories = rule && 'categories' in rule ? rule.categories : null
    return [0, 1, 0, 2].map((index) => {
        const option = options[index % options.length]
        return { value: option.label, passes: categories ? categories.includes(option.key) : null }
    })
}
