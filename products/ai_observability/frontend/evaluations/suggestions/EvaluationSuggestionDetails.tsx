import { Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { EvalSuggestionApi, EvalSuggestionFilterApi } from '../../generated/api.schemas'
import { UNITS } from './units'

/** "Only where review_lens is security-1 or security-2", in full, since a chip cuts multi-value filters short. */
function filterSummary(filters: readonly EvalSuggestionFilterApi[]): string {
    const parts = filters.map(({ key, value, operator }) => {
        const values = value.length > 1 ? `${value.slice(0, -1).join(', ')} or ${value[value.length - 1]}` : value[0]
        return `${key} ${operator === 'is_not' ? 'is not' : 'is'} ${values}`
    })
    return `Only where ${parts.join(' and ')}`
}

function facts(suggestion: EvalSuggestionApi): string[] {
    const { measured_failure_rate: rate, sample_size: sampleSize, estimated_weekly_runs: weeklyRuns } = suggestion
    const lines: string[] = []
    if (rate !== null && sampleSize !== null) {
        lines.push(
            `Failed on ${humanFriendlyNumber(Math.round(rate * sampleSize))} of ${humanFriendlyNumber(sampleSize)} traces sampled from the last 7 days`
        )
    }
    if (suggestion.kind === 'new_llm_judge') {
        const [unit, units] = UNITS[String(suggestion.draft.target)] ?? UNITS.trace
        const scope =
            suggestion.rollout_percentage >= 100
                ? `every matching ${unit}`
                : `${humanFriendlyNumber(suggestion.rollout_percentage)}% of matching ${units}`
        lines.push(`Runs on ${scope}${weeklyRuns !== null ? `, about ${humanFriendlyNumber(weeklyRuns)} a week` : ''}`)
    }
    if (suggestion.filters.length > 0) {
        lines.push(filterSummary(suggestion.filters))
    }
    if (suggestion.judge_model) {
        lines.push(`Judge model: ${suggestion.judge_model}`)
    }
    return lines
}

export function EvaluationSuggestionDetails({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 max-w-sm p-1 text-xs">
            <p className="m-0">{suggestion.reason}</p>
            <ul className="flex flex-col gap-1 m-0 pl-4 list-disc text-secondary">
                {facts(suggestion).map((fact) => (
                    <li key={fact}>{fact}</li>
                ))}
                {suggestion.similar_evaluation && (
                    <li>
                        Similar to{' '}
                        <Link
                            to={urls.aiObservabilityEvaluation(suggestion.similar_evaluation)}
                            data-attr="eval-suggestion-similar-eval"
                        >
                            {suggestion.similar_evaluation_name ?? 'an existing eval'}
                        </Link>
                    </li>
                )}
            </ul>
        </div>
    )
}
