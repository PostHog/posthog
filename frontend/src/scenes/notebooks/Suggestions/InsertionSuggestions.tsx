import { Editor as TTEditor } from '@tiptap/core'
import { useCallback } from 'react'
import { isCurrentNodeEmpty } from '../Notebook/utils'
import { FloatingMenu } from '@tiptap/react'
import { useValues } from 'kea'
import { insertionSuggestionsLogic } from './insertionSuggestionsLogic'

export function InsertionSuggestions({ editor }: { editor: TTEditor }): JSX.Element | null {
    const { activeSuggestion, previousNode } = useValues(insertionSuggestionsLogic({ editor }))
    const { Component } = activeSuggestion

    const shouldShow = useCallback((): boolean => {
        if (!editor) {
            return false
        }
        if (editor.view.hasFocus() && editor.isEditable && editor.isActive('paragraph') && isCurrentNodeEmpty(editor)) {
            return true
        }

        return false
    }, [editor])

    return editor ? (
        <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: 100, placement: 'left', offset: [0, 0] }}
            className="NotebookFloatingButton"
            shouldShow={shouldShow}
        >
            {Component && <Component previousNode={previousNode} />}
        </FloatingMenu>
    ) : null
}
