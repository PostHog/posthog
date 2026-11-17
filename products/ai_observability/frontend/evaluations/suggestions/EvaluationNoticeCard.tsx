import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvalSuggestionApi } from '../../generated/api.schemas'
import { EvaluationSuggestionDismissMenu } from './EvaluationSuggestionDismissMenu'
import { evaluationSuggestionsLogic } from './evaluationSuggestionsLogic'

/** A problem with an existing eval (kind fix_eval), next to the suggested evals. */
export function EvaluationNoticeCard({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    const { inFlight } = useValues(evaluationSuggestionsLogic)
    const { dismissSuggestion } = useActions(evaluationSuggestionsLogic)

    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor) ??
        (inFlight ? 'Wait for the current change to finish' : null)
    const hasPatch = Object.keys(suggestion.draft).length > 0

    return (
        <div
            className="flex flex-col h-full gap-1.5 p-3 rounded-lg border border-primary bg-surface-primary"
            data-attr={`eval-suggestion-${suggestion.kind}`}
        >
            {/* As tall as the Details button on suggestion cards, so headlines line up across the row. */}
            <div className="flex items-center min-h-6.5">
                <LemonTag type="warning" size="small">
                    Needs attention
                </LemonTag>
            </div>
            <h4 className="m-0 text-sm font-semibold">{suggestion.headline}</h4>
            <div className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
                <span className="text-secondary">Eval</span>
                <span className="font-medium">{suggestion.target_evaluation_name ?? 'An existing eval'}</span>
            </div>
            <p className="m-0 text-xs text-secondary">{suggestion.outcome}</p>
            <div className="flex flex-wrap items-center gap-2 mt-auto pt-1.5">
                {suggestion.target_evaluation && (
                    // The evaluation page shows the proposed change, and the suggestion closes once it is saved there.
                    <LemonButton
                        type="primary"
                        size="small"
                        to={
                            combineUrl(urls.aiObservabilityEvaluation(suggestion.target_evaluation), {
                                evaluation_tab: 'configuration',
                                suggestion: suggestion.id,
                            }).url
                        }
                        data-attr={hasPatch ? 'eval-suggestion-review-fix' : 'eval-suggestion-open-eval'}
                    >
                        {hasPatch ? 'Review fix' : 'Open eval'}
                    </LemonButton>
                )}
                <EvaluationSuggestionDismissMenu
                    loading={inFlight?.suggestionId === suggestion.id && inFlight.action === 'dismiss'}
                    disabledReason={disabledReason}
                    onDismiss={(reason) => dismissSuggestion(suggestion, reason)}
                />
            </div>
        </div>
    )
}
