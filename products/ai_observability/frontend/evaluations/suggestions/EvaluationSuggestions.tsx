import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, Spinner } from '@posthog/lemon-ui'

import type { EvalSuggestionApi } from '../../generated/api.schemas'
import { evaluationResultDrawerLogic } from '../overview/evaluationResultDrawerLogic'
import { evaluationsOverviewLogic } from '../overview/evaluationsOverviewLogic'
import { EvaluationSuggestionActions } from './EvaluationSuggestionActions'
import { EvaluationSuggestionDrawer } from './EvaluationSuggestionDrawer'
import { evaluationSuggestionsLogic } from './evaluationSuggestionsLogic'
import { EvaluationSuggestionsTurnOffMenu } from './EvaluationSuggestionsTurnOffMenu'
import { EvaluationSuggestionSummary } from './EvaluationSuggestionSummary'
import { JudgeSuggestionConfirmModal } from './JudgeSuggestionConfirmModal'

export function EvaluationSuggestions(): JSX.Element | null {
    const { suggestionList, suggestionListLoading, suggestionListLoadFailed, turningOff, openSuggestionId } =
        useValues(evaluationSuggestionsLogic)
    const { loadEvalSuggestions, turnOffSuggestions, openSuggestion } = useActions(evaluationSuggestionsLogic)
    const overviewLogic = evaluationsOverviewLogic.findMounted()
    const drawerLogic = evaluationResultDrawerLogic.findMounted()

    // A broken eval opens in the eval drawer, where its chart shows what is wrong. Without its results row, for
    // example on the empty page, the suggestion drawer shows it instead.
    const open = (suggestion: EvalSuggestionApi): void => {
        const target = suggestion.kind === 'fix_eval' ? suggestion.target_evaluation : null
        if (target && drawerLogic && overviewLogic?.values.rowsById.has(target)) {
            drawerLogic.actions.openDrawer(target)
        } else {
            openSuggestion(suggestion)
        }
    }

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
        <section className="flex flex-col gap-2" data-attr="eval-suggestions">
            <div className="flex items-start justify-between gap-2">
                <div>
                    <h3 className="m-0 text-base font-semibold">Suggested evals</h3>
                    <p className="m-0 text-xs text-secondary">
                        Found in a sample of your recent traces, best first. Open one to see the traces behind it.
                    </p>
                </div>
                <EvaluationSuggestionsTurnOffMenu loading={turningOff} onTurnOff={turnOffSuggestions} />
            </div>
            <LemonTable
                dataSource={suggestionList.results}
                rowKey="id"
                showHeader={false}
                onRow={(suggestion) => ({
                    onClick: () => open(suggestion),
                    className: 'cursor-pointer',
                    'data-attr': `eval-suggestion-${suggestion.kind}`,
                })}
                rowClassName={(suggestion) =>
                    suggestion.id === openSuggestionId ? 'bg-fill-highlight-100' : 'hover:bg-fill-highlight-50'
                }
                columns={[
                    {
                        key: 'suggestion',
                        render: (_, suggestion) => <EvaluationSuggestionSummary suggestion={suggestion} />,
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, suggestion) => (
                            // The row opens the drawer, so a click on an action stays with the action.
                            // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
                            <div onClick={(event) => event.stopPropagation()}>
                                <EvaluationSuggestionActions suggestion={suggestion} />
                            </div>
                        ),
                    },
                ]}
            />
            <JudgeSuggestionConfirmModal />
            <EvaluationSuggestionDrawer />
        </section>
    )
}
