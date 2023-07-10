// Helpers for Kea issue with double importing
import {
    JSONContent as TTJSONContent,
    Editor as TTEditor,
    ChainedCommands as EditorCommands,
    Range as EditorRange,
    getText,
} from '@tiptap/core'
import { NotebookNodeType } from '~/types'

// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface JSONContent extends TTJSONContent {}
// eslint-disable-next-line @typescript-eslint/no-empty-interface

export { ChainedCommands as EditorCommands, Range as EditorRange } from '@tiptap/core'

export interface NotebookEditor {
    getJSON: () => JSONContent
    setEditable: (editable: boolean) => void
    setContent: (content: JSONContent) => void
    isEmpty: () => boolean
    deleteRange: (range: EditorRange) => EditorCommands
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
        },
    })
}
