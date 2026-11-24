import type { LemonTagType } from '@posthog/lemon-ui'

import type { EvalSuggestionApi } from '../../generated/api.schemas'

export function suggestionKindLabel(suggestion: EvalSuggestionApi): string {
    switch (suggestion.kind) {
        case 'fix_eval':
            return 'Needs attention'
        case 'fix_prompt':
            return 'Prompt problem'
        case 'new_hog':
            return 'Code check'
        default:
            return suggestion.draft.evaluation_type === 'llm_judge' ? 'LLM judge' : 'Sentiment'
    }
}

/** Problems with something that exists stand out; new evals to add stay neutral. */
export function suggestionKindTagType(suggestion: EvalSuggestionApi): LemonTagType {
    return suggestion.kind === 'fix_eval' || suggestion.kind === 'fix_prompt' ? 'warning' : 'muted'
}
