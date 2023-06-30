// Helpers for Kea issue with double importing
import { JSONContent as TTJSONContent, Editor as TTEditor } from '@tiptap/core'

// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface JSONContent extends TTJSONContent {}
// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface Editor extends TTEditor {}

// Loosely based on https://github.com/ueberdosis/tiptap/blob/develop/packages/extension-floating-menu/src/floating-menu-plugin.ts#LL38C3-L55C4
export const isCurrentNodeEmpty = (editor: Editor): boolean => {
    const selection = editor.state.selection
    const { $anchor, empty } = selection
    const isEmptyTextBlock = $anchor.parent.isTextblock && !$anchor.parent.type.spec.code && !$anchor.parent.textContent

    if (empty && isEmptyTextBlock) {
        return true
    }

    return false
}
