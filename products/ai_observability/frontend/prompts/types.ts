import type { UserBasicType } from '~/types'

import type { LLMPromptApi, LLMPromptListApi, LLMPromptVersionSummaryApi } from '../generated/api.schemas'

// Derived from the generated schemas with deliberate overrides, applied by casts at the
// fetch boundaries:
// - prompt: the API accepts structured JSON payloads (typed unknown); this app only
//   reads and writes strings.
// - created_by: the generated UserBasicApi types hedgehog_config as nullable, which the
//   app's user components don't accept; runtime payloads match UserBasicType.
// - labels is omitted from LLMPrompt: the resolve flow replaces it with full label
//   objects (see ResolvedLLMPrompt in llmPromptLogic).
export type LLMPrompt = Omit<LLMPromptApi, 'prompt' | 'labels' | 'created_by'> & {
    prompt: string
    created_by: UserBasicType
    /** All labels on the prompt with the version each points to. Only present on list responses. */
    all_labels?: LLMPromptListApi['all_labels']
}

export type LLMPromptVersionSummary = Omit<LLMPromptVersionSummaryApi, 'created_by'> & {
    created_by: UserBasicType
}
