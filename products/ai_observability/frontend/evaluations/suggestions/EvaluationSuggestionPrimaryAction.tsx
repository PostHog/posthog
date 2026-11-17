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
