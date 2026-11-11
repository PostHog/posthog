import { JSONContent, RichContentNodeType } from './types'

const INLINE_NODE_TYPES = new Set<string>(['text', 'hardBreak', RichContentNodeType.Mention])

/**
 * Concatenates the text of a rich content document without a ProseMirror schema, so it needs no
 * editor code and no node or mark can throw. Blocks are separated by a blank line, as in the editor.
 */
export function richContentToText(node: JSONContent, mentionText: (id: number) => string): string {
    if (node.type === RichContentNodeType.Mention) {
        return node.attrs?.id != null ? mentionText(node.attrs.id) : ''
    }
    if (node.type === 'hardBreak') {
        return '\n'
    }
    if (node.type === 'image') {
        return node.attrs?.src ? `![${node.attrs.alt || 'image'}](${node.attrs.src})` : ''
    }
    const children = node.content ?? []
    const joined = children
        .map((child) => richContentToText(child, mentionText))
        .map((part, index) => {
            const isBlock = index > 0 && !INLINE_NODE_TYPES.has(children[index].type ?? '')
            return isBlock ? `\n\n${part}` : part
        })
        .join('')
    return (node.text ?? '') + joined
}
