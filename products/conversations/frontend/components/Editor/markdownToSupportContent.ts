import { JSONContent } from '@tiptap/core'
import { Link } from '@tiptap/extension-link'
import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

// The same nodes and marks as SUPPORT_EXTENSIONS. The support editor shows an empty draft when its
// content holds a node that its schema does not know, so the parser must not produce one.
const markdownManager = new MarkdownManager({
    extensions: [
        StarterKit.configure({
            link: false,
            heading: false,
            blockquote: false,
            horizontalRule: false,
            strike: false,
            underline: false,
        }),
        Link,
    ],
})

const bold = (node: JSONContent): JSONContent =>
    node.type === 'text' ? { ...node, marks: [...(node.marks ?? []), { type: 'bold' }] } : node

// The parser makes a heading node for a markdown heading even when no extension defines one.
function replaceHeadings(node: JSONContent): JSONContent {
    if (node.type === 'heading') {
        return { type: 'paragraph', content: (node.content ?? []).map(bold) }
    }
    return node.content ? { ...node, content: node.content.map(replaceHeadings) } : node
}

export function markdownToSupportContent(markdown: string): JSONContent {
    return replaceHeadings(markdownManager.parse(markdown) as JSONContent)
}
