import { JSONContent } from '@tiptap/core'

import {
    ChainedCommands as EditorCommands,
    FocusPosition as EditorFocusPosition,
    Range as EditorRange,
} from '@tiptap/core'

export type {
    ChainedCommands as EditorCommands,
    FocusPosition as EditorFocusPosition,
    Range as EditorRange,
} from '@tiptap/core'

export enum RichContentNodeType {
    Mention = 'ph-mention',
}

export interface RichContentEditor {
    getJSON: () => JSONContent
    getText: () => string
    getEndPosition: () => number
    getSelectedNode: () => Node | null
    getCurrentPosition: () => number
    getAdjacentNodes: (pos: number) => { previous: Node | null; next: Node | null }
    setEditable: (editable: boolean) => void
    setContent: (content: JSONContent) => void
    setSelection: (position: number) => void
    setTextSelection: (position: number | EditorRange) => void
    focus: (position?: EditorFocusPosition) => void
    chain: () => EditorCommands
    destroy: () => void
    getMarks: (type: string) => { id: string; pos: number }[]
    deleteRange: (range: EditorRange) => EditorCommands
    insertContent: (content: JSONContent) => void
    insertContentAfterNode: (position: number, content: JSONContent) => void
    pasteContent: (position: number, text: string) => void
    findNode: (position: number) => Node | null
    findNodePositionByAttrs: (attrs: Record<string, any>) => any
    nextNode: (position: number) => { node: Node; position: number } | null
    hasChildOfType: (node: Node, type: string) => boolean
    scrollToSelection: () => void
    scrollToPosition: (position: number) => void
}
