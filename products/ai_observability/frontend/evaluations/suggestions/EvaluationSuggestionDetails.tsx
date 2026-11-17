import type { ReactNode } from 'react'

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

export function EvaluationSuggestionDetails({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    const { draft, rollout_percentage: rollout, estimated_weekly_runs: weeklyRuns } = suggestion
    const rule = typeof draft.description === 'string' ? draft.description : ''
    const target = typeof draft.target === 'string' ? draft.target : undefined
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
                        <dt className="text-secondary">Sampling</dt>
                        <dd className="m-0">
                            {rollout >= 100
                                ? `Every matching ${unitNoun(target, 1)}`
                                : `${humanFriendlyNumber(rollout)}% of matching ${unitNoun(target, 2)}`}
                        </dd>
                        {weeklyRuns !== null && (
                            <>
                                <dt className="text-secondary">Estimated volume</dt>
                                <dd className="m-0">{`About ${humanFriendlyNumber(weeklyRuns)} per week`}</dd>
                            </>
                        )}
                        {suggestion.judge_model && (
                            <>
                                <dt className="text-secondary">Judge model</dt>
                                <dd className="m-0">{suggestion.judge_model}</dd>
                            </>
                        )}
                        {suggestion.filters.length > 0 && (
                            <>
                                <dt className="text-secondary">Applies to</dt>
                                <dd className="m-0">{filterSummary(suggestion.filters)}</dd>
                            </>
                        )}
                        {suggestion.similar_evaluation && (
                            <>
                                <dt className="text-secondary">Similar to</dt>
                                <dd className="m-0">
                                    <Link
                                        to={urls.aiObservabilityEvaluation(suggestion.similar_evaluation)}
                                        data-attr="eval-suggestion-similar-eval"
                                    >
                                        {suggestion.similar_evaluation_name ?? 'An existing eval'}
                                    </Link>
                                </dd>
                            </>
                        )}
                    </dl>
                </section>
            )}
        </div>
    )
}
