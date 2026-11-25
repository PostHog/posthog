import { Fragment, type ReactNode } from 'react'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { EvalSuggestionApi, EvalSuggestionFilterApi } from '../../generated/api.schemas'

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

/** Where the proposed evaluation runs, leaving out what the drawer's stats already show and what has no value. */
function configuration(suggestion: EvalSuggestionApi): [string, ReactNode][] {
    const rows: [string, ReactNode][] = []
    if (suggestion.filters.length > 0) {
        rows.push(['Applies to', filterSummary(suggestion.filters)])
    }
    if (suggestion.judge_model) {
        rows.push(['Judge model', suggestion.judge_model])
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

/** What the proposed eval checks and why, with where it would run. */
export function EvaluationSuggestionDetails({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    const rule = typeof suggestion.draft.description === 'string' ? suggestion.draft.description : ''
    const rows = suggestion.kind === 'new_hog' || suggestion.kind === 'new_llm_judge' ? configuration(suggestion) : []

    return (
        <div className="flex flex-col gap-2 text-sm">
            {rule && <p className="m-0">{withCodeSpans(rule)}</p>}
            {suggestion.reason && <p className="m-0 text-secondary">{suggestion.reason}</p>}
            {rows.length > 0 && (
                <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                    {rows.map(([label, value]) => (
                        <Fragment key={label}>
                            <dt className="text-secondary">{label}</dt>
                            <dd className="m-0">{value}</dd>
                        </Fragment>
                    ))}
                </dl>
            )}
        </div>
    )
}
