import { IconCheck, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import type { LemonTagProps } from '@posthog/lemon-ui'

import { formatNumericEvaluationScore, numericScorePasses } from '../evaluations/constants'
import type { EvaluationOutputConfig, EvaluationRun } from '../evaluations/types'
import { capitalize } from '../sentimentUtils'

type EvaluationResultLike = Pick<
    EvaluationRun,
    | 'status'
    | 'result'
    | 'result_type'
    | 'evaluation_type'
    | 'sentiment_label'
    | 'skipped'
    | 'score'
    | 'score_min'
    | 'score_max'
    | 'applicable'
>

interface EvaluationResultDisplay {
    type: LemonTagProps['type']
    icon: JSX.Element
    label: string
    sortValue: number
}

export interface EvaluationResultDisplayOptions {
    /** When true, the evaluation looks for a problem, so a true result is the undesirable one. */
    trueIsFailure?: boolean
    passingRule?: EvaluationOutputConfig['passing_rule']
}

const SENTIMENT_DISPLAY: Record<string, Pick<EvaluationResultDisplay, 'type' | 'icon' | 'sortValue'>> = {
    positive: { type: 'success', icon: <IconCheck />, sortValue: 3 },
    neutral: { type: 'none', icon: <IconMinus />, sortValue: 2 },
    negative: { type: 'danger', icon: <IconX />, sortValue: 1 },
}

export function isSentimentRun(run: EvaluationResultLike): boolean {
    return run.result_type === 'sentiment' || run.evaluation_type === 'sentiment' || !!run.sentiment_label
}

export function getEvaluationResultDisplay(
    run: EvaluationResultLike,
    options: EvaluationResultDisplayOptions = {}
): EvaluationResultDisplay {
    if (run.status === 'failed') {
        return { type: 'danger', icon: <IconWarning />, label: 'Error', sortValue: -2 }
    }
    if (run.status === 'running') {
        return { type: 'primary', icon: <IconMinus />, label: 'Running', sortValue: -1 }
    }
    // Before the result checks: a skip still carries `result: false` when the evaluation disallows
    // N/A, so reading the result first would report a session that was never graded as failing.
    if (run.skipped) {
        return { type: 'muted', icon: <IconMinus />, label: 'Skipped', sortValue: 0.4 }
    }
    if (run.result_type === 'numeric') {
        if (run.applicable === false) {
            return { type: 'muted', icon: <IconMinus />, label: 'N/A', sortValue: 0.5 }
        }
        if (run.score == null || !Number.isFinite(run.score)) {
            return { type: 'muted', icon: <IconMinus />, label: 'No score', sortValue: -1 }
        }
        const passed = numericScorePasses(run.score, options.passingRule)
        return {
            type: passed === null ? 'none' : passed ? 'success' : 'danger',
            icon: passed === null ? <IconMinus /> : passed ? <IconCheck /> : <IconX />,
            label: formatNumericEvaluationScore(run.score),
            sortValue: 4,
        }
    }
    if (isSentimentRun(run)) {
        const sentimentLabel = (run.sentiment_label || 'unknown').toLowerCase()
        const display = SENTIMENT_DISPLAY[sentimentLabel] ?? {
            type: 'muted' as const,
            icon: <IconMinus />,
            sortValue: 0,
        }
        return {
            ...display,
            label: capitalize(sentimentLabel),
        }
    }
    if (run.result === null) {
        return { type: 'muted', icon: <IconMinus />, label: 'N/A', sortValue: 0.5 }
    }
    // The label states the raw result either way; only the verdict it carries depends on polarity.
    const isDesirable = run.result !== Boolean(options.trueIsFailure)
    const label = run.result ? 'True' : 'False'
    return isDesirable
        ? { type: 'success', icon: <IconCheck />, label, sortValue: 1 }
        : { type: 'danger', icon: <IconX />, label, sortValue: 0 }
}

export function getEvaluationResultSortValue(
    run: EvaluationResultLike,
    options: EvaluationResultDisplayOptions = {}
): number {
    return getEvaluationResultDisplay(run, options).sortValue
}

export function compareEvaluationResults(
    a: EvaluationResultLike,
    b: EvaluationResultLike,
    aOptions: EvaluationResultDisplayOptions = {},
    bOptions: EvaluationResultDisplayOptions = aOptions
): number {
    const aRank = getEvaluationResultSortValue(a, aOptions)
    const bRank = getEvaluationResultSortValue(b, bOptions)
    return aRank === 4 && bRank === 4 ? a.score! - b.score! : aRank - bRank
}

export function EvaluationResultTag({
    run,
    trueIsFailure,
    passingRule,
    size,
}: {
    run: EvaluationResultLike
    trueIsFailure?: boolean
    passingRule?: EvaluationOutputConfig['passing_rule']
    size?: LemonTagProps['size']
}): JSX.Element {
    const { type, icon, label } = getEvaluationResultDisplay(run, { trueIsFailure, passingRule })
    return (
        <LemonTag type={type} icon={icon} size={size} title={run.score == null ? undefined : String(run.score)}>
            {label}
        </LemonTag>
    )
}
