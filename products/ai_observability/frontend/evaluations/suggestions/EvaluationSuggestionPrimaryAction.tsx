import { combineUrl } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { EvalSuggestionApi } from '../../generated/api.schemas'

export function EvaluationSuggestionPrimaryAction({
    suggestion,
    accepting,
    disabledReason,
    onAccept,
}: {
    suggestion: EvalSuggestionApi
    accepting: boolean
    disabledReason: string | null
    onAccept: () => void
}): JSX.Element | null {
    if (suggestion.kind === 'fix_prompt') {
        // A prompt problem has no evaluation to add: the team fixes the prompt, then dismisses the card.
        const promptName = typeof suggestion.draft.prompt_name === 'string' ? suggestion.draft.prompt_name : null
        return promptName ? (
            <LemonButton
                type="primary"
                size="small"
                to={urls.aiObservabilityPrompt(promptName)}
                data-attr="eval-suggestion-open-prompt"
            >
                Open prompt
            </LemonButton>
        ) : null
    }
    if (suggestion.kind === 'fix_eval') {
        if (!suggestion.target_evaluation) {
            return null
        }
        const hasPatch = Object.keys(suggestion.draft).length > 0
        // The evaluation page shows the proposed change, and the suggestion closes once it is saved there.
        return (
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
    }
    return (
        <LemonButton
            type="primary"
            size="small"
            loading={accepting}
            disabledReason={disabledReason}
            onClick={onAccept}
            data-attr="eval-suggestion-add"
        >
            Add eval
        </LemonButton>
    )
}
