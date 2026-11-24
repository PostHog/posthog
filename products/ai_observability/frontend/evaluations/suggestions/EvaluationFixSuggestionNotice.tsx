import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { EvaluationSuggestionActions } from './EvaluationSuggestionActions'
import { evaluationSuggestionsLogic } from './evaluationSuggestionsLogic'

/** What the suggestion pipeline found wrong with an evaluation, at the top of its drawer. */
export function EvaluationFixSuggestionNotice({ evaluationId }: { evaluationId: string }): JSX.Element | null {
    const { suggestionList } = useValues(evaluationSuggestionsLogic)
    const suggestion = suggestionList?.results.find(
        (result) => result.kind === 'fix_eval' && result.target_evaluation === evaluationId
    )
    if (!suggestion) {
        return null
    }
    return (
        <LemonBanner type="warning">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                    <p className="m-0 font-semibold">{suggestion.headline}</p>
                    <p className="m-0">{suggestion.outcome}</p>
                </div>
                <EvaluationSuggestionActions suggestion={suggestion} />
            </div>
        </LemonBanner>
    )
}
