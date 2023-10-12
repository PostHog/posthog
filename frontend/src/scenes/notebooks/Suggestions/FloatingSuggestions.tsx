import './FloatingSuggestions.scss'
import { Editor as TTEditor } from '@tiptap/core'
import { FloatingMenu } from '@tiptap/react'
import { useActions, useValues } from 'kea'
import { insertionSuggestionsLogic } from './insertionSuggestionsLogic'
import { isCurrentNodeEmpty } from '../Notebook/utils'
import { useEffect, useState } from 'react'
import { notebookLogic } from '../Notebook/notebookLogic'

export function FloatingSuggestions({ editor }: { editor: TTEditor }): JSX.Element | null {
    const logic = insertionSuggestionsLogic()
    const { activeSuggestion, previousNode } = useValues(logic)
    const { setEditor } = useActions(logic)
    const { editor: notebookEditor } = useValues(notebookLogic)

    const [shouldShow, setShouldShow] = useState(false)

    const { Component } = activeSuggestion

    useEffect(() => {
        setEditor(notebookEditor)
    }, [notebookEditor])

    const focusHandler = (): void => {
        console.log('got here')

        const currentNode = editor.state.doc.nodeAt(editor.state.selection.$head.pos)
        setShouldShow(!currentNode)
    }

    useEffect(() => {
        editor.on('selectionUpdate', focusHandler)
        return () => editor.off('selectionUpdate', focusHandler)
    }, [])

    return (
        <div className="FloatingSuggestion flex items-center justify-content">
            {Component && <Component previousNode={previousNode} editor={notebookEditor} />}
        </div>
    )

    // return (
    //     <FloatingMenu
    //         editor={editor}
    //         tippyOptions={{
    //             duration: [100, 0],
    //             placement: 'right',
    //             offset: [0, 0],
    //             // triggerTarget
    //             // getReferenceClientRect: () => ({
    //             //     width: 100,
    //             //     height: 100,
    //             //     left: 100,
    //             //     right: 200,
    //             //     top: 100,
    //             //     bottom: 200,
    //             // }),
    //         }}
    //         className="NotebookFloatingButton"
    //         shouldShow={({ editor }: { editor: TTEditor }) => {
    //             if (!editor) {
    //                 return false
    //             }
    //             if (
    //                 editor.view.hasFocus() &&
    //                 editor.isEditable &&
    //                 editor.isActive('paragraph') &&
    //                 isCurrentNodeEmpty(editor)
    //             ) {
    //                 return true
    //             }

    //             return false
    //         }}
    //     >
    //         <div className="FloatingSuggestion flex items-center justify-content">
    //             {Component && <Component previousNode={previousNode} editor={notebookEditor} />}
    //         </div>
    //     </FloatingMenu>
    // )
}
