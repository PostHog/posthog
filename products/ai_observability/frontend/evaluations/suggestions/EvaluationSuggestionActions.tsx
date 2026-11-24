import { useActions, useValues } from 'kea'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvalSuggestionApi } from '../../generated/api.schemas'
import { EvaluationSuggestionDismissMenu } from './EvaluationSuggestionDismissMenu'
import { EvaluationSuggestionPrimaryAction } from './EvaluationSuggestionPrimaryAction'
import { type SuggestionInFlight, evaluationSuggestionsLogic } from './evaluationSuggestionsLogic'

/** Add, open or dismiss a suggestion, in its table row and in its drawer. */
export function EvaluationSuggestionActions({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    const { inFlight } = useValues(evaluationSuggestionsLogic)
    const { acceptSuggestion, openJudgeConfirm, dismissSuggestion } = useActions(evaluationSuggestionsLogic)
    const running = (action: SuggestionInFlight['action']): boolean =>
        inFlight?.suggestionId === suggestion.id && inFlight.action === action
    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor) ??
        (inFlight ? 'Wait for the current change to finish' : null)

    return (
        <div className="flex w-max items-center justify-end gap-2">
            <EvaluationSuggestionPrimaryAction
                suggestion={suggestion}
                accepting={running('accept')}
                disabledReason={disabledReason}
                onAccept={() =>
                    // Only LLM judges cost money, so only they stop at the cost confirm.
                    suggestion.draft.evaluation_type === 'llm_judge'
                        ? openJudgeConfirm(suggestion)
                        : acceptSuggestion(suggestion)
                }
            />
            <EvaluationSuggestionDismissMenu
                loading={running('dismiss')}
                disabledReason={disabledReason}
                onDismiss={(reason) => dismissSuggestion(suggestion, reason)}
            />
        </div>
    )
}
