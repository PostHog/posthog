import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import { RichContentEditorType, RichContentNode } from 'lib/components/RichContentEditor/types'

import { InsertionSuggestion } from './InsertionSuggestion'
import SlashCommands from './SlashCommands'
import type { insertionSuggestionsLogicType } from './insertionSuggestionsLogicType'

export const insertionSuggestionsLogic = kea<insertionSuggestionsLogicType>([
    path(['scenes', 'notebooks', 'Suggestions', 'insertionSuggestionsLogic']),
    actions({
        setEditor: (editor: RichContentEditorType | null) => ({ editor }),
        setPreviousNode: (node: RichContentNode | null) => ({ node }),
        setSuggestions: (suggestions: InsertionSuggestion[]) => ({ suggestions }),
        resetSuggestions: true,
        onTab: true,
        onEscape: true,
    }),
    reducers({
        suggestions: [
            [] as InsertionSuggestion[],
            {
                setSuggestions: (_, { suggestions }) => suggestions,
            },
        ],
        previousNode: [
            null as RichContentNode | null,
            {
                setPreviousNode: (_, { node }) => node,
            },
        ],
        editor: [
            null as RichContentEditorType | null,
            {
                setEditor: (_, { editor }) => editor,
            },
        ],
    }),
    selectors({
        activeSuggestion: [
            (s) => [s.suggestions, s.previousNode],
            (suggestions: InsertionSuggestion[], previousNode: RichContentNode): InsertionSuggestion =>
                suggestions.find(
                    ({ dismissed, shouldShow }) =>
                        !dismissed && (typeof shouldShow === 'function' ? shouldShow({ previousNode }) : shouldShow)
                ) || SlashCommands,
        ],
    }),
    listeners(({ values, actions }) => ({
        resetSuggestions: () => {
            const nextSuggestions = values.suggestions.map((suggestion) => {
                return { ...suggestion, dismissed: false }
            })
            actions.setSuggestions(nextSuggestions)
        },

        onTab: () => {
            values.activeSuggestion?.onTab({ editor: values.editor, previousNode: values.previousNode })
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
    })),
    events(({ cache, actions }) => ({
        afterMount: () => {
            cache.onKeyDown = (e: KeyboardEvent) => {
                if (e.key === 'Tab') {
                    e.preventDefault()
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
    })),
])
