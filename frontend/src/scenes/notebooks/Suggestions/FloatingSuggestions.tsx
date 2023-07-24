import { Editor as TTEditor } from '@tiptap/core'
import { FloatingMenu } from '@tiptap/react'
import { useActions, useValues } from 'kea'
import { insertionSuggestionsLogic } from './insertionSuggestionsLogic'
import { isCurrentNodeEmpty } from '../Notebook/utils'
import { useEffect } from 'react'
import { notebookLogic } from '../Notebook/notebookLogic'

export function FloatingSuggestions({ editor }: { editor: TTEditor }): JSX.Element | null {
    const logic = insertionSuggestionsLogic()
    const { activeSuggestion, previousNode } = useValues(logic)
    const { setEditor } = useActions(logic)
    const { editor: notebookEditor } = useValues(notebookLogic)

    const { Component } = activeSuggestion

    useEffect(() => {
        setEditor(notebookEditor)
    }, [notebookEditor])

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
