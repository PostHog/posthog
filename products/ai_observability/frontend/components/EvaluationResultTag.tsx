import { IconCheck, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import type { LemonTagProps } from '@posthog/lemon-ui'

import type { EvaluationRun } from '../evaluations/types'
import { capitalize } from '../sentimentUtils'

type EvaluationResultLike = Pick<
    EvaluationRun,
    'status' | 'result' | 'result_type' | 'evaluation_type' | 'sentiment_label' | 'score_label' | 'score_value'
>

interface EvaluationResultDisplay {
    type: LemonTagProps['type']
    icon: JSX.Element
    label: string
    sortValue: number
}

const SENTIMENT_DISPLAY: Record<string, Pick<EvaluationResultDisplay, 'type' | 'icon' | 'sortValue'>> = {
    positive: { type: 'success', icon: <IconCheck />, sortValue: 3 },
    neutral: { type: 'none', icon: <IconMinus />, sortValue: 2 },
    negative: { type: 'danger', icon: <IconX />, sortValue: 1 },
}

const POSITIVE_SCORE_LABELS = new Set(['pass', 'passed', 'true', 'success'])
const NEGATIVE_SCORE_LABELS = new Set(['fail', 'failed', 'false', 'failure'])

export function isSentimentRun(run: EvaluationResultLike): boolean {
    return run.result_type === 'sentiment' || run.evaluation_type === 'sentiment' || !!run.sentiment_label
}

export function getEvaluationResultDisplay(run: EvaluationResultLike): EvaluationResultDisplay {
    if (run.status === 'failed') {
        return { type: 'danger', icon: <IconWarning />, label: 'Error', sortValue: -2 }
    }
    if (run.status === 'running') {
        return { type: 'primary', icon: <IconMinus />, label: 'Running', sortValue: -1 }
    }
    if (run.score_label || run.score_value != null) {
        const normalizedLabel = run.score_label?.toLowerCase()
        const label = run.score_label
            ? `${capitalize(run.score_label)}${run.score_value != null ? ` · ${run.score_value}` : ''}`
            : String(run.score_value)
        if (normalizedLabel && POSITIVE_SCORE_LABELS.has(normalizedLabel)) {
            return { type: 'success', icon: <IconCheck />, label, sortValue: run.score_value ?? 1 }
        }
        if (normalizedLabel && NEGATIVE_SCORE_LABELS.has(normalizedLabel)) {
            return { type: 'danger', icon: <IconX />, label, sortValue: run.score_value ?? 0 }
        }
        return { type: 'none', icon: <IconMinus />, label, sortValue: run.score_value ?? 0.5 }
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
    if (run.result) {
        return { type: 'success', icon: <IconCheck />, label: 'True', sortValue: 1 }
    }
    return { type: 'danger', icon: <IconX />, label: 'False', sortValue: 0 }
}

export function getEvaluationResultSortValue(run: EvaluationResultLike): number {
    return getEvaluationResultDisplay(run).sortValue
}

export function EvaluationResultTag({
    run,
    size,
}: {
    run: EvaluationResultLike
    size?: LemonTagProps['size']
}): JSX.Element {
    const { type, icon, label } = getEvaluationResultDisplay(run)
    return (
        <LemonTag type={type} icon={icon} size={size}>
            {label}
        </LemonTag>
    )
}
