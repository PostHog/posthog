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
        onTab: true,
        onEscape: true,
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
        previousNode: [
            () => [(_, props) => props.editor],
            (editor: TTEditor) => {
                const { $anchor } = editor.state.selection
                const node = $anchor.node(1)
                return editor.state.doc.childBefore($anchor.pos - node.nodeSize).node
            },
        ],
    },
    listeners: ({ props, values }) => ({
        onTab: () => {
            values.activeSuggestion.onTab({ editor: props.editor, previousNode: values.previousNode })
        },
        onEscape: () => {},
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
