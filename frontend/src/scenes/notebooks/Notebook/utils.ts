// Helpers for Kea issue with double importing
import {
    JSONContent as TTJSONContent,
    Editor as TTEditor,
    ChainedCommands as EditorCommands,
    FocusPosition as EditorFocusPosition,
    Range as EditorRange,
    getText,
} from '@tiptap/core'
import { Node as PMNode } from '@tiptap/pm/model'
import { NotebookNodeType } from '~/types'

/* eslint-disable @typescript-eslint/no-empty-interface */
export interface Node extends PMNode {}
export interface JSONContent extends TTJSONContent {}
/* eslint-enable @typescript-eslint/no-empty-interface */
// export type FocusPosition = number | boolean | 'start' | 'end' | 'all' | null

export {
    ChainedCommands as EditorCommands,
    Range as EditorRange,
    FocusPosition as EditorFocusPosition,
} from '@tiptap/core'

export interface NotebookEditor {
    getJSON: () => JSONContent
    setEditable: (editable: boolean) => void
    setContent: (content: JSONContent) => void
    focus: (position: EditorFocusPosition) => void
    destroy: () => void
    isEmpty: () => boolean
    deleteRange: (range: EditorRange) => EditorCommands
    insertContent: (content: JSONContent) => void
    insertContentAfterNode: (position: number, content: JSONContent) => void
    findNode: (position: number) => Node | null
    nextNode: (position: number) => { node: Node; position: number } | null
    hasChildOfType: (node: Node, type: string) => boolean
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
            [NotebookNodeType.Link]: ({ node }) => node.attrs.href,
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
