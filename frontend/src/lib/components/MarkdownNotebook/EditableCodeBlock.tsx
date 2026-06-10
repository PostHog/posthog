import { FormEvent, KeyboardEvent, useCallback, useLayoutEffect, useRef } from 'react'

import { isSelectionAnchoredInsideElement } from './domSelection'
import { TextSelectionPointerStartEvent } from './editorTypes'
import { NotebookBlockNode, NotebookCodeBlockNode, NotebookMode } from './types'

export function EditableCodeBlock({
    node,
    mode,
    setBlockRef,
    updateNode,
    deleteSelectedNotebookBlocks,
    handleSelectionChange,
    startTextSelectionPointer,
}: {
    node: NotebookCodeBlockNode
    mode: NotebookMode
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    deleteSelectedNotebookBlocks: () => boolean
    handleSelectionChange: () => void
    startTextSelectionPointer: (event: TextSelectionPointerStartEvent) => void
}): JSX.Element {
    const elementRef = useRef<HTMLPreElement | null>(null)
    const skipDomSyncForTextRef = useRef<string | null>(null)

    const setElementRef = useCallback(
        (element: HTMLPreElement | null): void => {
            elementRef.current = element
            setBlockRef(element)
        },
        [setBlockRef]
    )

    useLayoutEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        const selection = window.getSelection()
        const shouldSkipOwnInputSync =
            (document.activeElement === element || isSelectionAnchoredInsideElement(selection, element)) &&
            skipDomSyncForTextRef.current === node.text
        skipDomSyncForTextRef.current = null

        if (shouldSkipOwnInputSync || element.textContent === node.text) {
            return
        }

        element.textContent = node.text
    }, [node.id, node.text])

    const updateText = (text: string): void => {
        skipDomSyncForTextRef.current = text
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'code') {
                return currentNode
            }

            return { ...currentNode, text }
        })
    }

    const handleInput = (event: FormEvent<HTMLPreElement>): void => {
        updateText(event.currentTarget.textContent ?? '')
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLPreElement>): void => {
        if ((event.key === 'Backspace' || event.key === 'Delete') && deleteSelectedNotebookBlocks()) {
            event.preventDefault()
            event.stopPropagation()
        }
    }

    return (
        <pre
            className="MarkdownNotebook__code-block"
            ref={setElementRef}
            contentEditable={mode === 'edit'}
            data-markdown-notebook-node-id={node.id}
            data-placeholder="Code"
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            onMouseDown={startTextSelectionPointer}
            onPointerDown={startTextSelectionPointer}
            onTouchStart={startTextSelectionPointer}
            onMouseUp={handleSelectionChange}
            onKeyUp={handleSelectionChange}
            spellCheck={false}
            suppressContentEditableWarning
        />
    )
}
