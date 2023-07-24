import { kea } from 'kea'
import type { insertionSuggestionsLogicType } from './insertionSuggestionsLogicType'
import ReplayTimestampSuggestion from './ReplayTimestamp'
import SlashCommands from './SlashCommands'
import { InsertionSuggestion } from './InsertionSuggestion'
import { Node } from '@tiptap/pm/model'

const SUGGESTIONS = [ReplayTimestampSuggestion] as InsertionSuggestion[]
const DEFAULT_SUGGESTION: InsertionSuggestion = SlashCommands

export const insertionSuggestionsLogic = kea<insertionSuggestionsLogicType>({
    path: ['scenes', 'notebooks', 'Suggestions', 'insertionSuggestionsLogic'],

    actions: {
        setPreviousNode: (node) => ({ node }),
        setSuggestions: (suggestions: InsertionSuggestion[]) => ({ suggestions }),
        dismissSuggestion: (key: string) => ({ key }),
        resetSuggestions: true,
        onTab: true,
        onEscape: true,
    },

    reducers: {
        suggestions: [
            SUGGESTIONS,
            {
                setSuggestions: (_, { suggestions }) => suggestions,
            },
        ],
        previousNode: [
            null as Node | null,
            {
                setPreviousNode: (_, { node }) => node,
            },
        ],
    },

    selectors: {
        activeSuggestion: [
            (s) => [s.suggestions, s.previousNode],
            (suggestions: InsertionSuggestion[], previousNode: Node) =>
                suggestions.find(
                    ({ dismissed, shouldShow }) =>
                        !dismissed && (typeof shouldShow === 'function' ? shouldShow({ previousNode }) : shouldShow)
                ) || DEFAULT_SUGGESTION,
        ],
    },

    listeners: ({ values, actions }) => ({
        resetSuggestions: () => {
            const nextSuggestions = values.suggestions.map((suggestion) => {
                return { ...suggestion, dismissed: false }
            })
            actions.setSuggestions(nextSuggestions)
        },

        onTab: () => {
            values.activeSuggestion?.onTab({ previousNode: values.previousNode })
        },

        onEscape: () => {
            if (values.activeSuggestion) {
                const newSuggestion = { ...values.activeSuggestion, dismissed: true }
                const nextSuggestions = values.suggestions.map((suggestion) =>
                    suggestion === values.activeSuggestion ? newSuggestion : suggestion
                )
                actions.setSuggestions(nextSuggestions)
            }
        },
    }),

    events: ({ cache, actions }) => ({
        afterMount: () => {
            cache.onKeyDown = (e: KeyboardEvent) => {
                if (e.key === 'Tab') {
                    actions.onTab()
                } else if (e.key === 'Escape') {
                    actions.onEscape()
                }
            }
            window.addEventListener('keydown', cache.onKeyDown)
        },
        beforeUnmount: () => {
            window.removeEventListener('keydown', cache.onKeyDown)
        },
    }),
})
