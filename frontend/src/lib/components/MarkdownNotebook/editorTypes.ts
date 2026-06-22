import {
    MouseEvent as ReactMouseEvent,
    PointerEvent as ReactPointerEvent,
    ReactNode,
    TouchEvent as ReactTouchEvent,
} from 'react'

import {
    NotebookCodeBlockNode,
    NotebookComponentProps,
    NotebookInlineNode,
    NotebookListBlockNode,
    NotebookTextBlockNode,
    NotebookTextSelectionRange,
} from './types'

export type RestoreInlineSelectionRequest = {
    nodeId: string
    start: number
    end: number
    listItemIndex?: number
    listItemId?: string
    tableCell?: TableCellPosition
}

export type RestoreTextRange = NotebookTextSelectionRange & {
    listItemIndex?: number
}

export type RestoreTextSelectionRequest = {
    textRanges: RestoreTextRange[]
}

export type RestoreSelectionRequest = RestoreInlineSelectionRequest | RestoreTextSelectionRequest

export type InsertCommand = {
    key: string
    label: string
    category: string
    description?: string
    aliases?: string[]
    icon?: ReactNode
    closeOnRun?: boolean
    disabled?: boolean
    run: (targetNodeId: string) => void
}

/** Insertion primitives handed to caller-supplied insert commands so they can add blocks without
 * reaching into the editor's internals. The caller owns the command's label, icon, and behavior. */
export type MarkdownNotebookInsertMenuApi = {
    insertComponent: (targetNodeId: string, tagName: string, props: NotebookComponentProps) => void
}

export type InsertMenuState = {
    nodeId: string
    query: string
    selectedIndex: number
    mode?: 'tools' | 'ai'
    detached?: boolean
    removeNodeOnClose?: boolean
    source?: 'slash' | 'selection'
    selectedMarkdown?: string
    selectedRefId?: string
}

export type InsertMenuSelectionDirection = 'next' | 'previous'

export type InsertMenuPosition = {
    placement: 'above' | 'below'
    top: number
    left: number
    width: number
    maxHeight: number
}

export type FloatingToolbarTextRange = {
    node: NotebookTextBlockNode
    range: NotebookTextSelectionRange
}

export type FloatingToolbarCodeRange = {
    node: NotebookCodeBlockNode
    range: NotebookTextSelectionRange
}

export type FloatingToolbarListItemRange = {
    node: NotebookListBlockNode
    itemIndex: number
    range: NotebookTextSelectionRange
}

export type FloatingToolbarState = {
    textRanges: FloatingToolbarTextRange[]
    codeRanges: FloatingToolbarCodeRange[]
    listItemRanges: FloatingToolbarListItemRange[]
    selectedMarkdown: string
    placement: 'above' | 'below'
    top: number
    left: number
    isLinkEditorOpen?: boolean
}

export type FloatingToolbarPointerAnchor = {
    x: number
    y: number
    placement: 'above' | 'below'
}

export type FloatingToolbarPosition = Pick<FloatingToolbarState, 'placement' | 'top' | 'left'>

export type TextBlockStyle = 'paragraph' | 'blockquote' | 'code' | 1 | 2 | 3

export type TextSelectionPointerState = {
    originX: number
    originY: number
    lastX: number
    lastY: number
}

export type TextSelectionPointerStartEvent =
    | ReactMouseEvent<HTMLElement>
    | ReactPointerEvent<HTMLElement>
    | ReactTouchEvent<HTMLElement>

export type InlineLinkPasteResult = {
    children: NotebookInlineNode[]
    start: number
    end: number
}

export type TableSection = 'header' | 'body'

export type TableCellPosition = {
    section: TableSection
    rowIndex: number
    columnIndex: number
}

export const FLOATING_TOOLBAR_ESTIMATED_HEIGHT = 36

export const INSERT_MENU_GAP = 12

export const INSERT_MENU_MAX_HEIGHT = 448

export const INSERT_MENU_MIN_HEIGHT = 120

export const INSERT_MENU_PLACEHOLDER = 'Search for a tool'

export const INSERT_MENU_WIDTH = 384

export const INSERT_MENU_VIEWPORT_PADDING = 12

export const MAX_UNDO_HISTORY_ENTRIES = 100

export const FLOATING_TOOLBAR_REVEAL_DELAY_MS = 200

export const FLOATING_TOOLBAR_GAP = 8

export const NOTEBOOK_TITLE_PLACEHOLDER = 'Untitled notebook'

export const NOTEBOOK_EDITABLE_BLOCK_SELECTOR =
    '.MarkdownNotebook__text-block, .MarkdownNotebook__list-item-content, .MarkdownNotebook__table-cell-content, .MarkdownNotebook__code-block'
