import { type Editor, Extension, type JSONContent, Node } from '@tiptap/core'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import { Markdown } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

import { LinkExtension } from 'lib/components/RichContentEditor/LinkExtension'

// The parser drops `\[`-style escape tokens unless something handles them, which would lose the character.
const MarkdownEscape = Extension.create({
    name: 'markdownEscape',
    markdownTokenName: 'escape',
    parseMarkdown: (token) => ({ type: 'text', text: token.text }),
})

function safeHref(src: string): string | null {
    try {
        const url = new URL(src)
        return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
    } catch {
        return null
    }
}

/**
 * A Markdown image, kept so saving doesn't drop it, and shown as a link to the image rather than the image itself:
 * every viewer would otherwise load an image from any URL an editor typed.
 */
const ImageLink = Node.create({
    name: 'image',
    inline: true,
    group: 'inline',
    atom: true,
    addAttributes: () => ({ src: { default: '' }, alt: { default: '' }, title: { default: null } }),
    renderHTML: ({ node }) => {
        const { src, alt } = node.attrs as { src: string; alt: string }
        const href = safeHref(src)
        const label = alt || src
        return href ? ['a', { href, target: '_blank', rel: 'noopener noreferrer' }, label] : ['span', {}, label]
    },
    parseMarkdown: (token, helpers) =>
        helpers.createNode('image', { src: token.href, alt: token.text, title: token.title || null }),
    renderMarkdown: (node) => {
        const { src = '', alt = '', title } = (node.attrs ?? {}) as { src?: string; alt?: string; title?: string }
        const destination = /[\s()<>]/.test(src) ? `<${src.replace(/[<>]/g, encodeURIComponent)}>` : src
        const quotedTitle = title ? ` "${title.replace(/"/g, '\\"')}"` : ''
        return `![${alt.replace(/[[\]\\]/g, '\\$&')}](${destination}${quotedTitle})`
    },
})

/** The extensions that decide what a text tile's Markdown can hold, shared by the editor and its round-trip tests. */
export const MARKDOWN_EXTENSIONS = [
    StarterKit.configure({ link: false, underline: false }),
    // Pasting a URL over selected text links it.
    LinkExtension.configure({ openOnClick: false }),
    Table,
    TableRow,
    TableHeader,
    TableCell,
    TaskList,
    TaskItem.configure({ nested: true }),
    ImageLink,
    MarkdownEscape,
    Markdown,
]

/** Empty Markdown parses to a document with no paragraph, which leaves no line to type on or show the hint in. */
export function markdownContent(text: string): { content: string | JSONContent; contentType?: 'markdown' } {
    return text.trim()
        ? { content: text, contentType: 'markdown' }
        : { content: { type: 'doc', content: [{ type: 'paragraph' }] } }
}

const INLINE_SYNTAX = /[\\`*_[\]~<]/g
const BLOCK_START = /^(\s*)([#>+-]|\d+[.)])/

function escapeText(node: JSONContent, startsBlock: boolean): JSONContent {
    if (node.marks?.some((mark) => mark.type === 'code')) {
        return node
    }
    const text = (node.text ?? '').replace(INLINE_SYNTAX, '\\$&')
    return { ...node, text: startsBlock ? text.replace(BLOCK_START, '$1\\$2') : text }
}

// The serializer writes text as it is, so a literal `*` or `#` would read back as Markdown syntax.
function escapeLiterals(node: JSONContent): JSONContent {
    if (node.type === 'codeBlock' || !node.content) {
        return node
    }
    return {
        ...node,
        content: node.content.map((child, index) =>
            child.type === 'text' ? escapeText(child, index === 0) : escapeLiterals(child)
        ),
    }
}

/** The editor's content as Markdown that reads back to the same content. */
export function serializeMarkdown(editor: Editor): string {
    return editor.markdown ? editor.markdown.serialize(escapeLiterals(editor.getJSON())) : editor.getText()
}
