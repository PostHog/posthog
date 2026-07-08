import { IconCheck, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import type { LemonTagProps } from '@posthog/lemon-ui'

import type { EvaluationRun } from '../evaluations/types'
import { capitalize } from '../sentimentUtils'

type EvaluationResultLike = Pick<
    EvaluationRun,
    'status' | 'result' | 'result_type' | 'evaluation_type' | 'sentiment_label'
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
