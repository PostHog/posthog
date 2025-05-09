import { kea } from 'kea'

// We will import QUESTION_SUGGESTIONS_DATA and SuggestionGroup from QuestionSuggestions.tsx
import { QUESTION_SUGGESTIONS_DATA, type SuggestionGroup } from './QuestionSuggestions'
import type { questionSuggestionsLogicType } from './questionSuggestionsLogicType'

export const questionSuggestionsLogic = kea<questionSuggestionsLogicType>({
    path: ['scenes', 'max', 'questionSuggestionsLogic'],
    actions: {
        setActiveSuggestionGroupLabel: (label: string | null) => ({ label }),
    },
    reducers: {
        activeSuggestionGroupLabel: [
            null as string | null,
            {
                setActiveSuggestionGroupLabel: (_: any, { label }: { label: string | null }): string | null => label,
            },
        ],
    },
    selectors: {
        suggestionGroups: [
            () => [], // Kea selector typing hint
            (): readonly SuggestionGroup[] => QUESTION_SUGGESTIONS_DATA,
        ],
        activeSuggestionGroup: [
            (s) => [s.activeSuggestionGroupLabel, s.suggestionGroups],
            (label: string | null, groups: readonly SuggestionGroup[]): SuggestionGroup | undefined => {
                if (!label) {
                    return undefined
                }
                return groups.find((sg: SuggestionGroup) => sg.label === label)
            },
        ],
    },
})
