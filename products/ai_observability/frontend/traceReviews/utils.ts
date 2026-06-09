import type { TraceReview, TraceReviewScore } from './types'
export {
    getBooleanConfig,
    getCategoricalConfig,
    getNumericConfig,
} from '../scoreDefinitions/scoreDefinitionConfigUtils'
import { getBooleanConfig, getCategoricalConfig } from '../scoreDefinitions/scoreDefinitionConfigUtils'

const DEFAULT_BOOLEAN_TRUE_LABEL = 'Yes'
const DEFAULT_BOOLEAN_FALSE_LABEL = 'No'

export function getTraceReviewScores(review: Pick<TraceReview, 'scores'> | null | undefined): TraceReviewScore[] {
    return Array.isArray(review?.scores) ? review.scores : []
}

export function formatNumericTraceReviewScore(value: string | number | null | undefined): string {
    if (value === null || value === undefined || value === '') {
        return ''
    }

    return String(value)
        .replace(/(\.\d*?)0+$/, '$1')
        .replace(/\.$/, '')
}

export function getTraceReviewScoreDisplayValue(score: TraceReviewScore): string {
    if (score.definition_kind === 'categorical') {
        const config = getCategoricalConfig(score.definition_config)
        const selectedKeys = score.categorical_values || []

        if (selectedKeys.length === 0) {
            return 'Reviewed'
        }

        const optionLabels = new Map(config.options.map((option) => [option.key, option.label]))
        return selectedKeys.map((optionKey) => optionLabels.get(optionKey) || optionKey).join(', ')
    }

    if (score.definition_kind === 'numeric') {
        return formatNumericTraceReviewScore(score.numeric_value)
    }

    const config = getBooleanConfig(score.definition_config)
    if (score.boolean_value === true) {
        return config.true_label || DEFAULT_BOOLEAN_TRUE_LABEL
    }

    return config.false_label || DEFAULT_BOOLEAN_FALSE_LABEL
}

export function getTraceReviewScoreTagLabel(score: TraceReviewScore): string {
    return `${score.definition_name}: ${getTraceReviewScoreDisplayValue(score)}`
}

export function getVisibleTraceReviewScores(
    review: Pick<TraceReview, 'scores'> | null | undefined,
    maxVisibleScores: number
): TraceReviewScore[] {
    return getTraceReviewScores(review).slice(0, Math.max(0, maxVisibleScores))
}

export function getHiddenTraceReviewScoreCount(
    review: Pick<TraceReview, 'scores'> | null | undefined,
    maxVisibleScores: number
): number {
    return Math.max(
        0,
        getTraceReviewScores(review).length - getVisibleTraceReviewScores(review, maxVisibleScores).length
    )
}

export function getTraceReviewDisplayValue(review: TraceReview): string {
    const scores = getTraceReviewScores(review)

    if (scores.length === 0) {
        return 'Reviewed'
    }

    if (scores.length === 1) {
        const score = scores[0]
        const summary = getTraceReviewScoreTagLabel(score)
        return summary.length <= 24 ? summary : '1 score'
    }

    return `${scores.length} scores`
}

export function getTraceReviewStatusDisplayValue(review: TraceReview | null): string {
    if (!review) {
        return 'Not reviewed'
    }

    const scores = getTraceReviewScores(review)

    if (scores.length === 0) {
        return 'Reviewed'
    }

    return scores.length === 1 ? `Reviewed: ${getTraceReviewDisplayValue(review)}` : `Reviewed: ${scores.length} scores`
}

export function getTraceReviewTagType(review: TraceReview): 'success' | 'completion' {
    return getTraceReviewScores(review).length === 0 ? 'success' : 'completion'
}

export function getTraceReviewStatusTagType(review: TraceReview | null): 'success' | 'completion' | 'muted' {
    if (!review) {
        return 'muted'
    }

    return getTraceReviewTagType(review)
}

export function getTraceReviewerName(review: TraceReview): string | null {
    const reviewer = review.reviewed_by

    if (!reviewer) {
        return null
    }

    if (reviewer.first_name) {
        return reviewer.first_name
    }

    if (reviewer.email) {
        return reviewer.email
    }

    if (reviewer.distinct_id) {
        return reviewer.distinct_id
    }

    return null
}
