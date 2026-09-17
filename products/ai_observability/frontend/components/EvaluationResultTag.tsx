import { IconCheck, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import type { LemonTagProps } from '@posthog/lemon-ui'

import type { EvaluationRun } from '../evaluations/types'
import { capitalize } from '../sentimentUtils'

type EvaluationResultLike = Pick<
    EvaluationRun,
    'status' | 'result' | 'result_type' | 'evaluation_type' | 'sentiment_label' | 'skipped'
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

export function EvaluationResultTag({
    run,
    trueIsFailure,
    size,
}: {
    run: EvaluationResultLike
    trueIsFailure?: boolean
    size?: LemonTagProps['size']
}): JSX.Element {
    const { type, icon, label } = getEvaluationResultDisplay(run, { trueIsFailure })
    return (
        <LemonTag type={type} icon={icon} size={size}>
            {label}
        </LemonTag>
    )
}
