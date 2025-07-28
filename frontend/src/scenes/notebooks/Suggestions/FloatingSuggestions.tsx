import './FloatingSuggestions.scss'

import { useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useEffect, useState } from 'react'

import { isCurrentNodeEmpty } from '../utils'
import { insertionSuggestionsLogic } from './insertionSuggestionsLogic'
import { richContentEditorLogic } from 'lib/components/RichContentEditor/richContentEditorLogic'

export function FloatingSuggestions(): JSX.Element | null {
    const logic = insertionSuggestionsLogic()
    const { ttEditor, richContentEditor } = useValues(richContentEditorLogic)
    const { activeSuggestion, previousNode } = useValues(logic)
    const { ref: setRef, height } = useResizeObserver()
    const [shouldShow, setShouldShow] = useState<boolean>(false)

    const [position, setPosition] = useState<{ top: number }>({ top: 0 })

    const { Component } = activeSuggestion

    const handleUpdate = (): void => {
        const selection = window.getSelection()

        if (selection && selection.anchorNode && selection.anchorNode.parentElement) {
            if (selection.anchorNode.nodeType === Node.ELEMENT_NODE) {
                const editorPos = ttEditor.view.dom.getBoundingClientRect()
                const selectionPos = (selection.anchorNode as HTMLElement).getBoundingClientRect()

                setPosition({ top: selectionPos.top - editorPos.top })
            }
        }

        setShouldShow(
            ttEditor.view.hasFocus() &&
                ttEditor.isEditable &&
                ttEditor.isActive('paragraph') &&
                isCurrentNodeEmpty(ttEditor)
        )
    }

    useEffect(() => {
        handleUpdate()
    }, [height, handleUpdate])

    useEffect(() => {
        ttEditor.on('update', handleUpdate)
        ttEditor.on('selectionUpdate', handleUpdate)
        setRef(ttEditor.view.dom)
        return () => {
            ttEditor.off('update', handleUpdate)
            ttEditor.off('selectionUpdate', handleUpdate)
        }
    }, [handleUpdate, ttEditor, setRef, ttEditor.view.dom])

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="NotebookFloatingButton" style={{ top: position.top }}>
            {shouldShow && (
                <div className="FloatingSuggestion flex items-center justify-content">
                    {Component && <Component previousNode={previousNode} editor={richContentEditor} />}
                </div>
            )}
        </div>
    )
}
