// Helpers for Kea issue with double importing
import { LemonButtonProps } from '@posthog/lemon-ui'
import {
    ChainedCommands as EditorCommands,
    FocusPosition as EditorFocusPosition,
    JSONContent as TTJSONContent,
    Range as EditorRange,
} from '@tiptap/core'
import { Node as PMNode } from '@tiptap/pm/model'

import { NotebookNodeResource } from '~/types'

export interface Node extends PMNode {}
export interface JSONContent extends TTJSONContent {}

export type {
    ChainedCommands as EditorCommands,
    FocusPosition as EditorFocusPosition,
    Range as EditorRange,
} from '@tiptap/core'

export type CustomNotebookNodeAttributes = Record<string, any>

export type NotebookNodeAttributes<T extends CustomNotebookNodeAttributes> = T & {
    nodeId: string
    height?: string | number
    title?: string
    __init?: {
        expanded?: boolean
        showSettings?: boolean
    }
    // TODO: Type this more specifically to be our supported nodes only
    children?: NotebookNodeResource[]
}

// NOTE: Pushes users to use the parsed "attributes" instead
export type NotebookNode = Omit<PMNode, 'attrs'>

export type NotebookNodeAttributeProperties<T extends CustomNotebookNodeAttributes> = {
    attributes: NotebookNodeAttributes<T>
    updateAttributes: (attributes: Partial<NotebookNodeAttributes<T>>) => void
}

export type NotebookNodeProps<T extends CustomNotebookNodeAttributes> = NotebookNodeAttributeProperties<T>

export type NotebookNodeSettings =
    // using 'any' here shouldn't be necessary but, I couldn't figure out how to set a generic on the notebookNodeLogic props
    (({ attributes, updateAttributes }: NotebookNodeAttributeProperties<any>) => JSX.Element) | null

export type NotebookNodeAction = Pick<LemonButtonProps, 'icon'> & {
    text: string
    onClick: () => void
}

export interface NotebookEditor {
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
    findCommentPosition: (markId: string) => number | null
    getMarks: (type: string) => { id: string; pos: number }[]
    removeComment: (pos: number) => void
    deleteRange: (range: EditorRange) => EditorCommands
    insertContent: (content: JSONContent | JSONContent[]) => void
    insertContentAfterNode: (position: number, content: JSONContent | JSONContent[]) => void
    pasteContent: (position: number, text: string) => void
    findNode: (position: number) => Node | null
    findNodePositionByAttrs: (attrs: Record<string, any>) => any
    nextNode: (position: number) => { node: Node; position: number } | null
    hasChildOfType: (node: Node, type: string) => boolean
    scrollToSelection: () => void
    scrollToPosition: (position: number) => void
}
