// Helpers for Kea issue with double importing
import {
    ChainedCommands as EditorCommands,
    Editor as TTEditor,
    FocusPosition as EditorFocusPosition,
    getText,
    JSONContent as TTJSONContent,
    Range as EditorRange,
} from '@tiptap/core'
import { Node as PMNode } from '@tiptap/pm/model'
import { NodeViewProps } from '@tiptap/react'
import { NotebookNodeType } from '~/types'

export interface Node extends PMNode {}
export interface JSONContent extends TTJSONContent {}

export {
    ChainedCommands as EditorCommands,
    Range as EditorRange,
    FocusPosition as EditorFocusPosition,
} from '@tiptap/core'

export type CustomNotebookNodeAttributes = Record<string, any>

export type NotebookNodeAttributes<T extends CustomNotebookNodeAttributes> = T & {
    nodeId: string
    title: string | null
    height?: string | number
}

// NOTE: Pushes users to use the parsed "attributes" instead
export type NotebookNode = Omit<PMNode, 'attrs'>

export type NotebookNodeAttributeProperties<T extends CustomNotebookNodeAttributes> = {
    attributes: NotebookNodeAttributes<T>
    updateAttributes: (attributes: Partial<NotebookNodeAttributes<T>>) => void
}

export type NotebookNodeViewProps<T extends CustomNotebookNodeAttributes> = Omit<
    NodeViewProps,
    'node' | 'updateAttributes'
> &
    NotebookNodeAttributeProperties<T> & {
        node: NotebookNode
    }

export type NotebookNodeWidget = {
    key: string
    label: string
    icon: JSX.Element
    // using 'any' here shouldn't be necessary but I couldn't figure out how to set a generic on the notebookNodeLogic props
    Component: ({ attributes, updateAttributes }: NotebookNodeAttributeProperties<any>) => JSX.Element
}

export interface NotebookEditor {
    getJSON: () => JSONContent
    getSelectedNode: () => Node | null
    getAdjacentNodes: (pos: number) => { previous: Node | null; next: Node | null }
    setEditable: (editable: boolean) => void
    setContent: (content: JSONContent) => void
    setSelection: (position: number) => void
    focus: (position: EditorFocusPosition) => void
    destroy: () => void
    isEmpty: () => boolean
    deleteRange: (range: EditorRange) => EditorCommands
    insertContent: (content: JSONContent) => void
    insertContentAfterNode: (position: number, content: JSONContent) => void
    findNode: (position: number) => Node | null
    findNodePositionByAttrs: (attrs: Record<string, any>) => any
    nextNode: (position: number) => { node: Node; position: number } | null
    hasChildOfType: (node: Node, type: string) => boolean
    scrollToSelection: () => void
}

// Loosely based on https://github.com/ueberdosis/tiptap/blob/develop/packages/extension-floating-menu/src/floating-menu-plugin.ts#LL38C3-L55C4
export const isCurrentNodeEmpty = (editor: TTEditor): boolean => {
    const selection = editor.state.selection
    const { $anchor, empty } = selection
    const isEmptyTextBlock =
        $anchor.parent.isTextblock && !$anchor.parent.type.spec.code && !textContent($anchor.parent)

    if (empty && isEmptyTextBlock) {
        return true
    }

    return false
}

const textContent = (node: any): string => {
    return getText(node, {
        blockSeparator: ' ',
        textSerializers: {
            [NotebookNodeType.ReplayTimestamp]: ({ node }) => `${node.attrs.playbackTime || '00:00'}: `,
        },
    })
}

export function defaultNotebookContent(title?: string, content?: JSONContent[]): JSONContent {
    const initialContent = [
        {
            type: 'heading',
            attrs: { level: 1 },
            content: [{ type: 'text', text: title }],
        },
    ] as JSONContent[]

    if (content) {
        initialContent.push(...content)
    }

    return { type: 'doc', content: initialContent }
}
