import { useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { TraceDrawerHost } from '../../redesign/trace/TraceDrawerHost'
import { EvaluationNoticeCard } from './EvaluationNoticeCard'
import { EvaluationSuggestionCard } from './EvaluationSuggestionCard'
import { SUGGESTION_EXAMPLES_LIST, evaluationSuggestionsLogic } from './evaluationSuggestionsLogic'
import { EvaluationSuggestionsTurnOffMenu } from './EvaluationSuggestionsTurnOffMenu'
import { JudgeSuggestionConfirmModal } from './JudgeSuggestionConfirmModal'

export function EvaluationSuggestions(): JSX.Element | null {
    const { suggestionList, suggestionListLoading, suggestionListLoadFailed, turningOff } =
        useValues(evaluationSuggestionsLogic)
    const { loadEvalSuggestions, turnOffSuggestions } = useActions(evaluationSuggestionsLogic)

    if (suggestionListLoadFailed) {
        return (
            <div className="flex flex-wrap items-center gap-2 text-sm text-secondary">
                <span>Couldn't load suggested evals.</span>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    loading={suggestionListLoading}
                    onClick={() => loadEvalSuggestions()}
                    data-attr="eval-suggestions-retry"
                >
                    Try again
                </LemonButton>
            </div>
        )
    }
    // Most projects get no suggestions, so a placeholder during the first load would flash and vanish for them.
    if (!suggestionList) {
        return null
    }
    if (suggestionList.results.length === 0) {
        return suggestionList.pending ? (
            <div className="flex items-center gap-2 text-sm text-secondary">
                <Spinner />
                <span>Preparing suggestions from your traces…</span>
            </div>
        ) : null
    }
    return (
        <section className="@container/suggestions flex flex-col gap-2" data-attr="eval-suggestions">
            <div className="flex items-center justify-between gap-2">
                <h3 className="m-0 text-base font-semibold">Suggested evals</h3>
                <EvaluationSuggestionsTurnOffMenu loading={turningOff} onTurnOff={turnOffSuggestions} />
            </div>
            <div className="grid grid-cols-1 gap-2 @min-[40rem]/suggestions:grid-cols-2 @min-[64rem]/suggestions:grid-cols-3">
                {suggestionList.results.map((suggestion) =>
                    suggestion.kind === 'fix_eval' ? (
                        <EvaluationNoticeCard key={suggestion.id} suggestion={suggestion} />
                    ) : (
                        <EvaluationSuggestionCard key={suggestion.id} suggestion={suggestion} />
                    )
                )}
            </div>
            <JudgeSuggestionConfirmModal />
            <TraceDrawerHost listId={SUGGESTION_EXAMPLES_LIST} />
        </section>
    )
}
