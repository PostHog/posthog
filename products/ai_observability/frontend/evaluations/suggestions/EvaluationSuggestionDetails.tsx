import { Fragment, type ReactNode } from 'react'

import { Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { EvalSuggestionApi, EvalSuggestionFilterApi } from '../../generated/api.schemas'
import { unitNoun } from './units'

/** "Only where review_lens is security-1 or security-2", in full, since a chip cuts multi-value filters short. */
function filterSummary(filters: readonly EvalSuggestionFilterApi[]): string {
    const parts = filters.map(({ key, value, operator }) => {
        if (operator === 'is_not_set') {
            return `${key} is not set`
        }
        const values = value.length > 1 ? `${value.slice(0, -1).join(', ')} or ${value[value.length - 1]}` : value[0]
        return `${key} ${operator === 'is_not' ? 'is not' : 'is'} ${values}`
    })
    return `Only where ${parts.join(' and ')}`
}

/** The rule names properties in backticks; show those as code without pulling in a markdown renderer. */
function withCodeSpans(text: string): ReactNode[] {
    return text.split(/`([^`]+)`/).map((part, index) => (index % 2 ? <code key={index}>{part}</code> : part))
}

/** The proposed evaluation's settings, as label and value pairs, leaving out the ones the card has no value for. */
function configuration(suggestion: EvalSuggestionApi): [string, ReactNode][] {
    const { rollout_percentage: rollout, estimated_weekly_runs: weeklyRuns } = suggestion
    const target = typeof suggestion.draft.target === 'string' ? suggestion.draft.target : undefined
    const rows: [string, ReactNode][] = [
        [
            'Sampling',
            rollout >= 100
                ? `Every matching ${unitNoun(target, 1)}`
                : `${humanFriendlyNumber(rollout)}% of matching ${unitNoun(target, 2)}`,
        ],
    ]
    if (weeklyRuns !== null) {
        rows.push(['Estimated volume', `About ${humanFriendlyNumber(weeklyRuns)} per week`])
    }
    if (suggestion.judge_model) {
        rows.push(['Judge model', suggestion.judge_model])
    }
    if (suggestion.filters.length > 0) {
        rows.push(['Applies to', filterSummary(suggestion.filters)])
    }
    if (suggestion.similar_evaluation) {
        rows.push([
            'Similar to',
            <Link
                key="similar"
                to={urls.aiObservabilityEvaluation(suggestion.similar_evaluation)}
                data-attr="eval-suggestion-similar-eval"
            >
                {suggestion.similar_evaluation_name ?? 'An existing eval'}
            </Link>,
        ])
    }
    return rows
}

export function EvaluationSuggestionDetails({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    const rule = typeof suggestion.draft.description === 'string' ? suggestion.draft.description : ''
    const proposesEval = suggestion.kind === 'new_hog' || suggestion.kind === 'new_llm_judge'

    return (
        <div className="flex flex-col gap-3 max-w-sm p-1 text-xs">
            {rule && (
                <section>
                    <h5 className="m-0 mb-0.5 text-xs font-semibold">Rule</h5>
                    <p className="m-0">{withCodeSpans(rule)}</p>
                </section>
            )}
            {suggestion.reason && (
                <section>
                    <h5 className="m-0 mb-0.5 text-xs font-semibold">Why it matters</h5>
                    <p className="m-0">{suggestion.reason}</p>
                </section>
            )}
            {proposesEval && (
                <section>
                    <h5 className="m-0 mb-1 text-xs font-semibold">Proposed configuration</h5>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 m-0">
                        {configuration(suggestion).map(([label, value]) => (
                            <Fragment key={label}>
                                <dt className="text-secondary">{label}</dt>
                                <dd className="m-0">{value}</dd>
                            </Fragment>
                        ))}
                    </dl>
                </section>
            )}
        </div>
    )
}
