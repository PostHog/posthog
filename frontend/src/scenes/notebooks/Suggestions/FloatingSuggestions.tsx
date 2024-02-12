import './FloatingSuggestions.scss'

import { Editor as TTEditor } from '@tiptap/core'
import { useActions, useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useEffect, useState } from 'react'

import { notebookLogic } from '../Notebook/notebookLogic'
import { isCurrentNodeEmpty } from '../Notebook/utils'
import { insertionSuggestionsLogic } from './insertionSuggestionsLogic'

export function FloatingSuggestions({ editor }: { editor: TTEditor }): JSX.Element | null {
    const logic = insertionSuggestionsLogic()
    const { activeSuggestion, previousNode } = useValues(logic)
    const { setEditor } = useActions(logic)
    const { editor: notebookEditor } = useValues(notebookLogic)
    const { ref: setRef, height } = useResizeObserver()
    const [shouldShow, setShouldShow] = useState<boolean>(false)

    const [position, setPosition] = useState<{ top: number }>({ top: 0 })

    const { Component } = activeSuggestion

    const handleUpdate = (): void => {
        const selection = window.getSelection()

        if (selection && selection.anchorNode && selection.anchorNode.parentElement) {
            if (selection.anchorNode.nodeType === Node.ELEMENT_NODE) {
                const editorPos = editor.view.dom.getBoundingClientRect()
                const selectionPos = (selection.anchorNode as HTMLElement).getBoundingClientRect()

                setPosition({ top: selectionPos.top - editorPos.top })
            }
        }

        setShouldShow(
            editor.view.hasFocus() && editor.isEditable && editor.isActive('paragraph') && isCurrentNodeEmpty(editor)
        )
    }

    useEffect(() => {
        setEditor(notebookEditor)
    }, [notebookEditor])

    useEffect(() => {
        handleUpdate()
    }, [height])

    useEffect(() => {
        editor.on('update', handleUpdate)
        editor.on('selectionUpdate', handleUpdate)
        setRef(editor.view.dom)
        return () => {
            editor.off('update', handleUpdate)
            editor.off('selectionUpdate', handleUpdate)
        }
    }, [])

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="NotebookFloatingButton" style={{ top: position.top }}>
            {shouldShow && (
                <div className="FloatingSuggestion flex items-center justify-content">
                    {Component && notebookEditor && <Component previousNode={previousNode} editor={notebookEditor} />}
                </div>
            )}
        </div>
    )
}
