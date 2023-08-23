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
import { NotebookNodeType, NotebookNodeWidgetSettings } from '~/types'

/* eslint-disable @typescript-eslint/no-empty-interface */
export interface Node extends PMNode {}
export interface JSONContent extends TTJSONContent {}
/* eslint-enable @typescript-eslint/no-empty-interface */

export {
    ChainedCommands as EditorCommands,
    Range as EditorRange,
    FocusPosition as EditorFocusPosition,
} from '@tiptap/core'

export type NotebookNodeAttributes = Record<string, any>
type NotebookNode<T extends NotebookNodeAttributes> = Omit<PMNode, 'attrs'> & {
    attrs: T & {
        nodeId: string
        height?: string | number
    }
}

export type NotebookNodeViewProps<T extends NotebookNodeAttributes> = Omit<NodeViewProps, 'node'> & {
    node: NotebookNode<T>
}

export type NotebookNodeWidget = {
    key: string
    label: string
    icon: JSX.Element
    Component: ({ attributes, updateAttributes }: NotebookNodeWidgetSettings) => JSX.Element
}

export interface NotebookEditor {
    getJSON: () => JSONContent
    getSelectedNode: () => Node | null
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
