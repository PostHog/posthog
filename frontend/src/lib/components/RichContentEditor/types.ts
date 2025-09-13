import {
    ChainedCommands as EditorCommands,
    FocusPosition as EditorFocusPosition,
    Range as EditorRange,
    JSONContent as TTJSONContent,
} from '@tiptap/core'
import { Node as PMNode } from '@tiptap/pm/model'

export interface RichContentNode extends PMNode {}
export interface JSONContent extends TTJSONContent {}

export type {
    ChainedCommands as EditorCommands,
    FocusPosition as EditorFocusPosition,
    Range as EditorRange,
    Editor as TTEditor,
} from '@tiptap/core'

export enum RichContentNodeType {
    Mention = 'ph-mention',
}

export interface RichContentEditorType {
    getJSON: () => JSONContent
    getEndPosition: () => number
    getSelectedNode: () => RichContentNode | null
    getCurrentPosition: () => number
    getAdjacentNodes: (pos: number) => { previous: RichContentNode | null; next: RichContentNode | null }
    setEditable: (editable: boolean) => void
    setContent: (content: JSONContent) => void
    setSelection: (position: number) => void
    setTextSelection: (position: number | EditorRange) => void
    focus: (position?: EditorFocusPosition) => void
    chain: () => EditorCommands
    destroy: () => void
    getMarks: (type: string) => { id: string; pos: number }[]
    setMark: (id: string) => void
    getMentions: () => number[]
    isActive: (name: string, attributes?: {}) => boolean
    deleteRange: (range: EditorRange) => EditorCommands
    insertContent: (content: JSONContent) => void
    insertContentAfterNode: (position: number, content: JSONContent) => void
    pasteContent: (position: number, text: string) => void
    findNode: (position: number) => RichContentNode | null
    findNodePositionByAttrs: (attrs: Record<string, any>) => any
    nextNode: (position: number) => { node: RichContentNode; position: number } | null
    hasChildOfType: (node: RichContentNode, type: string) => boolean
    scrollToSelection: () => void
    scrollToPosition: (position: number) => void
    clear: () => void
}
