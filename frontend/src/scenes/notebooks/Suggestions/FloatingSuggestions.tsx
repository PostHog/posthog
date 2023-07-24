import { Editor as TTEditor } from '@tiptap/core'
import { FloatingMenu } from '@tiptap/react'
import { useValues } from 'kea'
import { insertionSuggestionsLogic } from './insertionSuggestionsLogic'
import { isCurrentNodeEmpty } from '../Notebook/utils'

export function FloatingSuggestions({ editor }: { editor: TTEditor }): JSX.Element | null {
    const logic = insertionSuggestionsLogic()
    const { activeSuggestion, previousNode } = useValues(logic)

    const { Component } = activeSuggestion

    return (
        <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: [100, 0], placement: 'left', offset: [0, 0] }}
            className="NotebookFloatingButton"
            shouldShow={({ editor }: { editor: TTEditor }) => {
                if (!editor) {
                    return false
                }
                if (
                    editor.view.hasFocus() &&
                    editor.isEditable &&
                    editor.isActive('paragraph') &&
                    isCurrentNodeEmpty(editor)
                ) {
                    return true
                }

                return false
            }}
        >
            {Component && <Component previousNode={previousNode} />}
        </FloatingMenu>
    )
}
