import { kea } from 'kea'
import type { insertionSuggestionsLogicType } from './insertionSuggestionsLogicType'
import ReplayTimestampSuggestion from './ReplayTimestamp'
import SlashCommands from './SlashCommands'
import { Editor as TTEditor } from '@tiptap/core'
import { InsertionSuggestion } from './InsertionSuggestion'
import { Node } from '@tiptap/pm/model'

type InsertionSuggestionsLogicProps = {
    editor: TTEditor
}

const SUGGESTIONS = [ReplayTimestampSuggestion] as InsertionSuggestion[]
const DEFAULT_SUGGESTION: InsertionSuggestion = SlashCommands

export const insertionSuggestionsLogic = kea<insertionSuggestionsLogicType>({
    props: {} as InsertionSuggestionsLogicProps,
    path: ['scenes', 'notebooks', 'Suggestions', 'insertionSuggestionsLogic'],

    actions: {
        dismissSuggestion: (key: string) => ({ key }),
        resetSuggestions: true,
        onTab: true,
        onEscape: true,
    },

    selectors: {
        previousNode: [
            () => [(_, props) => props.editor],
            (editor: TTEditor) => {
                const { $anchor } = editor.state.selection
                const node = $anchor.node(1)
                return editor.state.doc.childBefore($anchor.pos - node.nodeSize).node
            },
        ],
        activeSuggestion: [
            (s) => [s.previousNode],
            (previousNode: Node) =>
                SUGGESTIONS.find(({ dismissed, shouldShow }) =>
                    !dismissed && typeof shouldShow === 'function' ? shouldShow({ previousNode }) : shouldShow
                ) || DEFAULT_SUGGESTION,
        ],
    },

    listeners: ({ props, values }) => ({
        resetSuggestions: () => {
            SUGGESTIONS.forEach((suggestion) => (suggestion.dismissed = false))
        },
        onTab: () => {
            values.activeSuggestion?.onTab({ editor: props.editor, previousNode: values.previousNode })
        },
        onEscape: () => {
            if (values.activeSuggestion && SUGGESTIONS.includes(values.activeSuggestion)) {
                values.activeSuggestion.dismissed = true
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
