import { useActions, useValues } from 'kea'

import { IconEye } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonTag } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvalSuggestionApi } from '../../generated/api.schemas'
import { EvaluationSuggestionCost } from './EvaluationSuggestionCost'
import { EvaluationSuggestionDetails } from './EvaluationSuggestionDetails'
import { EvaluationSuggestionDismissMenu } from './EvaluationSuggestionDismissMenu'
import { EvaluationSuggestionObservation } from './EvaluationSuggestionObservation'
import { EvaluationSuggestionPrimaryAction } from './EvaluationSuggestionPrimaryAction'
import { evaluationSuggestionsLogic, type SuggestionInFlight } from './evaluationSuggestionsLogic'

function methodLabel(suggestion: EvalSuggestionApi): string {
    if (suggestion.kind === 'fix_prompt') {
        return 'Prompt problem'
    }
    if (suggestion.kind === 'new_hog') {
        return 'Code check'
    }
    return suggestion.draft.evaluation_type === 'llm_judge' ? 'LLM judge' : 'Sentiment'
}

/** A suggested eval to add, or a prompt problem. A broken existing eval renders as `EvaluationNoticeCard`. */
export function EvaluationSuggestionCard({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    const { inFlight } = useValues(evaluationSuggestionsLogic)
    const { acceptSuggestion, openJudgeConfirm, dismissSuggestion, openExamples } =
        useActions(evaluationSuggestionsLogic)

    const running = (action: SuggestionInFlight['action']): boolean =>
        inFlight?.suggestionId === suggestion.id && inFlight.action === action
    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor) ??
        (inFlight ? 'Wait for the current change to finish' : null)
    const isPromptProblem = suggestion.kind === 'fix_prompt'
    const isJudge = suggestion.draft.evaluation_type === 'llm_judge'
    const examples = suggestion.evidence.length

    return (
        <div
            className="flex flex-col h-full gap-1.5 p-3 rounded-lg border border-primary bg-surface-primary"
            data-attr={`eval-suggestion-${suggestion.kind}`}
        >
            <div className="flex items-center justify-between gap-2">
                <LemonTag type={isPromptProblem ? 'warning' : 'muted'} size="small">
                    {methodLabel(suggestion)}
                </LemonTag>
                <LemonDropdown
                    overlay={<EvaluationSuggestionDetails suggestion={suggestion} />}
                    placement="bottom-end"
                    closeOnClickInside={false}
                >
                    <LemonButton size="xsmall" type="tertiary" data-attr="eval-suggestion-details">
                        Details
                    </LemonButton>
                </LemonDropdown>
            </div>
            <h4 className="m-0 text-sm font-semibold">{suggestion.headline}</h4>
            <p className="m-0 text-xs text-secondary">{suggestion.outcome}</p>
            {suggestion.observation && (
                <EvaluationSuggestionObservation
                    observation={suggestion.observation}
                    scope={suggestion.observation_scope}
                />
            )}
            <div className="flex flex-col gap-2 mt-auto pt-1.5">
                {!isPromptProblem && (
                    <EvaluationSuggestionCost
                        usesProvider={isJudge}
                        weeklyCostUsd={suggestion.estimated_weekly_cost_usd}
                    />
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <EvaluationSuggestionPrimaryAction
                        suggestion={suggestion}
                        accepting={running('accept')}
                        disabledReason={disabledReason}
                        onAccept={() =>
                            // Only LLM judges cost money, so only they stop at the cost confirm.
                            isJudge ? openJudgeConfirm(suggestion) : acceptSuggestion(suggestion)
                        }
                    />
                    <EvaluationSuggestionDismissMenu
                        loading={running('dismiss')}
                        disabledReason={disabledReason}
                        onDismiss={(reason) => dismissSuggestion(suggestion, reason)}
                    />
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
        </div>
    )
}
