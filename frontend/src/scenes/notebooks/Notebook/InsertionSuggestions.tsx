import { Extension, Editor as TTEditor } from '@tiptap/core'
import { useCallback } from 'react'
import { isCurrentNodeEmpty } from './utils'
import { FloatingMenu } from '@tiptap/react'
import ReplayTimestampSuggestion from '../Suggestions/ReplayTimestamp'
import SlashCommands from '../Suggestions/SlashCommands'

type InsertionSuggestion = {
    shouldShow: boolean | (({ editor }: { editor: TTEditor }) => boolean)
    Component: React.FunctionComponent
}

const SUGGESTIONS = [ReplayTimestampSuggestion, SlashCommands] as InsertionSuggestion[]

export function InsertionSuggestions({ editor }: { editor: TTEditor }): JSX.Element | null {
    const shouldShow = useCallback((): boolean => {
        if (!editor) {
            return false
        }
        if (editor.view.hasFocus() && editor.isEditable && editor.isActive('paragraph') && isCurrentNodeEmpty(editor)) {
            return true
        }

        return false
    }, [editor])

    const Component = [...SUGGESTIONS].find(({ shouldShow }) => {
        return typeof shouldShow === 'function' ? shouldShow({ editor }) : shouldShow
    })?.Component

    console.log('Component', Component)

    return editor && Component ? (
        <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: 100, placement: 'left' }}
            className="NotebookFloatingButton"
            shouldShow={shouldShow}
        >
            <Component />
        </FloatingMenu>
    ) : null
}

export const InsertionSuggestionsExtension = Extension.create({
    addKeyboardShortcuts() {
        return {
            Enter: ({}) => {
                console.log('Enter pressed')
                return false
            },
            Tab: ({}) => {
                console.log('Tab pressed')
                return false
            },
            Esc: ({}) => {
                console.log('Esc pressed')
                return false
            },
        }
    },
})
