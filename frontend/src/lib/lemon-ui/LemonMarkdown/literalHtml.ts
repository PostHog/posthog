interface MarkdownNode {
    type: string
    value?: string
    children?: MarkdownNode[]
}

// Parents whose children are blocks. A text node there needs a paragraph around it.
const BLOCK_PARENTS = new Set(['root', 'blockquote', 'listItem', 'footnoteDefinition'])

function convertHtmlNodes(parent: MarkdownNode): void {
    const children = parent.children ?? []
    for (const [index, child] of children.entries()) {
        if (child.type === 'html') {
            const text: MarkdownNode = { type: 'text', value: child.value ?? '' }
            children[index] = BLOCK_PARENTS.has(parent.type) ? { type: 'paragraph', children: [text] } : text
        } else {
            convertHtmlNodes(child)
        }
    }
}

/**
 * Remark plugin that changes each raw HTML node into a text node, so text such as `<example>`
 * shows as typed. Without it, the renderer drops raw HTML (`skipHtml`) and the text is lost.
 * The markdown parser decides what is raw HTML, so code, autolinks and escapes keep their usual
 * meaning, and React escapes the text when it renders it.
 */
export function remarkLiteralHtml(): (tree: MarkdownNode) => void {
    return convertHtmlNodes
}
