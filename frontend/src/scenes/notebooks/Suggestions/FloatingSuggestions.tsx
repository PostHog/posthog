import './FloatingSuggestions.scss'

import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { getTiptapEditorDom } from 'lib/components/MarkdownEditor/shared/tiptapEditorDom'
import { richContentEditorLogic } from 'lib/components/RichContentEditor/richContentEditorLogic'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { isCurrentNodeEmpty } from '../utils'
import { insertionSuggestionsLogic } from './insertionSuggestionsLogic'

export function FloatingSuggestions(): JSX.Element | null {
    const logic = insertionSuggestionsLogic()
    const { ttEditor, richContentEditor } = useValues(richContentEditorLogic)
    const { activeSuggestion, previousNode } = useValues(logic)
    const { ref: setRef, height } = useResizeObserver()
    const [shouldShow, setShouldShow] = useState<boolean>(false)

    const [position, setPosition] = useState<{ top: number }>({ top: 0 })

    const { Component } = activeSuggestion

    const handleUpdate = (): void => {
        const dom = getTiptapEditorDom(ttEditor)
        if (!dom) {
            return
        }

        const selection = window.getSelection()

        if (selection && selection.anchorNode && selection.anchorNode.parentElement) {
            if (selection.anchorNode.nodeType === Node.ELEMENT_NODE) {
                const editorPos = dom.getBoundingClientRect()
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
    }, [height]) // oxlint-disable-line exhaustive-deps

    useOnMountEffect(() => {
        const attachToDom = (): void => {
            const dom = getTiptapEditorDom(ttEditor)
            if (dom) {
                setRef(dom)
            }
        }

        ttEditor.on('update', handleUpdate)
        ttEditor.on('selectionUpdate', handleUpdate)
        // Re-point the observer whenever the view (re)mounts — AI notebooks rebuild the editor.
        ttEditor.on('mount', attachToDom)
        attachToDom() // 'mount' only fires on future (re)mounts, so attach now if the view is already up

        return () => {
            ttEditor.off('update', handleUpdate)
            ttEditor.off('selectionUpdate', handleUpdate)
            ttEditor.off('mount', attachToDom)
        }
    })

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
