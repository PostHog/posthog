import { kea } from 'kea'
import type { insertionSuggestionsLogicType } from './insertionSuggestionsLogicType'
import ReplayTimestampSuggestion from './ReplayTimestamp'
import SlashCommands from './SlashCommands'
import { Editor as TTEditor } from '@tiptap/core'

type InsertionSuggestion = {
    shouldShow: boolean | (({ editor }: { editor: TTEditor }) => boolean)
    Component: React.FunctionComponent
    onTab: ({ editor }: { editor: TTEditor }) => void
}

type InsertionSuggestionsLogicProps = {
    editor: TTEditor
}

const SUGGESTIONS = [ReplayTimestampSuggestion, SlashCommands]

export const insertionSuggestionsLogic = kea<insertionSuggestionsLogicType>({
    props: {} as InsertionSuggestionsLogicProps,
    path: ['scenes', 'notebooks', 'Suggestions', 'insertionSuggestionsLogic'],

    actions: {
        dismissSuggestion: (key: string) => ({ key }),
        resetSuggestions: true,
    },
    reducers: () => ({
        suggestions: [
            SUGGESTIONS as InsertionSuggestion[],
            {
                resetSuggestions: () => [...SUGGESTIONS],
            },
        ],
    }),

    selectors: {
        activeSuggestion: [
            (s) => [s.suggestions, (_, props) => props.editor],
            (suggestions: InsertionSuggestion[], editor: TTEditor) =>
                suggestions.find(({ shouldShow }) => {
                    return true
                    return typeof shouldShow === 'function' ? shouldShow({ editor }) : shouldShow
                }),
        ],
    },

    events: ({ cache, props, values }) => ({
        afterMount: () => {
            cache.onKeyDown = (e: KeyboardEvent) => {
                if (e.key === 'Tab') {
                    values.activeSuggestion.onTab({ editor: props.editor })
                } else if (e.key === 'Escape') {
                    console.log('Escaped')
                }
            }
            window.addEventListener('keydown', cache.onKeyDown)
        },
        beforeUnmount: () => {
            window.removeEventListener('keydown', cache.onKeyDown)
        },
    }),
})
