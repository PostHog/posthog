import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconEye } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvalSuggestionApi, EvalSuggestionDismissReasonEnumApi } from '../../generated/api.schemas'
import { EvaluationSuggestionDetails } from './EvaluationSuggestionDetails'
import { evaluationSuggestionsLogic, type SuggestionInFlight } from './evaluationSuggestionsLogic'

const DISMISS_REASONS: { reason: EvalSuggestionDismissReasonEnumApi; label: string }[] = [
    { reason: 'not_relevant', label: 'Not relevant' },
    { reason: 'already_covered', label: 'Already covered' },
    { reason: 'too_noisy', label: 'Too noisy' },
    { reason: 'fixed_cause', label: 'Fixed the cause' },
]

function kindLabel(suggestion: EvalSuggestionApi): string {
    if (suggestion.kind === 'fix_eval') {
        return 'Broken eval'
    }
    if (suggestion.kind === 'new_hog') {
        return 'Code check'
    }
    return suggestion.draft.evaluation_type === 'llm_judge' ? 'LLM judge' : 'Sentiment'
}

export function EvaluationSuggestionCard({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    const { inFlight } = useValues(evaluationSuggestionsLogic)
    const { acceptSuggestion, openJudgeConfirm, dismissSuggestion, openExamples } =
        useActions(evaluationSuggestionsLogic)

    const running = (action: SuggestionInFlight['action']): boolean =>
        inFlight?.suggestionId === suggestion.id && inFlight.action === action
    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor) ??
        (inFlight ? 'Wait for the current change to finish' : null)
    const isFix = suggestion.kind === 'fix_eval'
    const hasPatch = Object.keys(suggestion.draft).length > 0
    const examples = suggestion.evidence.length

    return (
        <div
            className="flex flex-col h-full gap-1.5 p-3 rounded-lg border border-primary bg-surface-primary"
            data-attr={`eval-suggestion-${suggestion.kind}`}
        >
            {/* As tall as the Details button, so headlines line up across cards with and without one. */}
            <div className="flex items-center justify-between gap-2 min-h-6.5">
                <LemonTag type={isFix ? 'warning' : 'muted'} size="small">
                    {kindLabel(suggestion)}
                </LemonTag>
                {!isFix && (
                    <LemonDropdown
                        overlay={<EvaluationSuggestionDetails suggestion={suggestion} />}
                        placement="bottom-end"
                        closeOnClickInside={false}
                    >
                        <LemonButton size="xsmall" type="tertiary" data-attr="eval-suggestion-details">
                            Details
                        </LemonButton>
                    </LemonDropdown>
                )}
            </div>
            <h4 className="m-0 text-sm font-semibold">{suggestion.headline}</h4>
            <p className="m-0 text-xs text-secondary">{suggestion.outcome}</p>
            <div className="flex flex-wrap items-center gap-2 mt-auto pt-1.5">
                {isFix ? (
                    suggestion.target_evaluation && (
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
                    )
                ) : (
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={running('accept')}
                        disabledReason={disabledReason}
                        onClick={() =>
                            // Only LLM judges cost money, so only they stop at the cost confirm.
                            suggestion.draft.evaluation_type === 'llm_judge'
                                ? openJudgeConfirm(suggestion)
                                : acceptSuggestion(suggestion)
                        }
                        data-attr="eval-suggestion-add"
                    >
                        Add eval
                    </LemonButton>
                )}
                <LemonMenu
                    items={[
                        {
                            title: 'Why dismiss it?',
                            items: DISMISS_REASONS.map(({ reason, label }) => ({
                                label,
                                onClick: () => dismissSuggestion(suggestion, reason),
                            })),
                        },
                        {
                            items: [
                                {
                                    label: 'Dismiss without a reason',
                                    onClick: () => dismissSuggestion(suggestion, null),
                                },
                            ],
                        },
                    ]}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={running('dismiss')}
                        disabledReason={disabledReason}
                        data-attr="eval-suggestion-dismiss"
                    >
                        Dismiss
                    </LemonButton>
                </LemonMenu>
                {examples > 0 && (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconEye />}
                        className="ml-auto"
                        onClick={() => openExamples(suggestion)}
                        data-attr="eval-suggestion-examples"
                    >
                        {`See ${pluralize(examples, 'example')}`}
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
