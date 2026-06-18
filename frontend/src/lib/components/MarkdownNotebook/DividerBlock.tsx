import clsx from 'clsx'
import { KeyboardEvent } from 'react'

import { InsertMenuSelectionDirection } from './editorTypes'
import { NotebookComponentBlockNode, NotebookMode } from './types'

export function DividerBlock({
    node,
    mode,
    isSelected,
    setBlockRef,
    deleteNode,
    deleteSelectedNotebookBlocks,
    insertParagraphAfterNode,
    moveFocusToAdjacentNode,
}: {
    node: NotebookComponentBlockNode
    mode: NotebookMode
    isSelected: boolean
    setBlockRef: (element: HTMLElement | null) => void
    deleteNode: () => void
    deleteSelectedNotebookBlocks: () => boolean
    insertParagraphAfterNode: () => void
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
}): JSX.Element {
    const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || event.target !== event.currentTarget) {
            return
        }

        if (event.key === 'Backspace' || event.key === 'Delete') {
            event.preventDefault()
            if (!deleteSelectedNotebookBlocks()) {
                deleteNode()
            }
            return
        }

        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (moveFocusToAdjacentNode(node.id, event.key === 'ArrowDown' ? 'next' : 'previous', 0)) {
                event.preventDefault()
            }
            return
        }

        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            insertParagraphAfterNode()
        }
    }

    return (
        <div
            className={clsx(
                'MarkdownNotebook__divider-block',
                isSelected && 'MarkdownNotebook__divider-block--selected'
            )}
            ref={setBlockRef}
            contentEditable={false}
            tabIndex={mode === 'edit' ? 0 : undefined}
            role="separator"
            aria-label="Divider"
            onKeyDown={handleKeyDown}
        >
            <hr />
        </div>
    )
}
