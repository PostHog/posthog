import './FloatingSuggestions.scss'
import { Editor as TTEditor } from '@tiptap/core'
import { BubbleMenu, FloatingMenu } from '@tiptap/react'
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
        <BubbleMenu
            editor={editor}
            tippyOptions={{
                interactive: false,
                duration: [100, 0],
                // placement: 'right',
                // offset: [24, 0],
            }}
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
            <div className="FloatingSuggestion flex items-center justify-content">
                {Component && <Component previousNode={previousNode} editor={notebookEditor} />}
            </div>
        </BubbleMenu>
    )
}
