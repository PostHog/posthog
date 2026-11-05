import { fromMarkdown } from 'mdast-util-from-markdown'

import { remarkLiteralHtml } from './literalHtml'
import { XSS_PAYLOADS } from './xssPayloads'

interface MarkdownNode {
    type: string
    value?: string
    children?: MarkdownNode[]
}

function literalTree(markdown: string): MarkdownNode {
    const tree = fromMarkdown(markdown) as MarkdownNode
    remarkLiteralHtml()(tree)
    return tree
}

function nodes(node: MarkdownNode): MarkdownNode[] {
    return [node, ...(node.children ?? []).flatMap(nodes)]
}

function visibleText(tree: MarkdownNode): string {
    return nodes(tree)
        .map((node) => node.value ?? '')
        .join('')
}

describe('remarkLiteralHtml', () => {
    it.each([
        ['an inline tag', 'keep <example> intact', 'keep <example> intact'],
        ['a closing tag', 'keep </example> intact', 'keep </example> intact'],
        ['a comment', 'a <!-- note --> b', 'a <!-- note --> b'],
        ['a tag block', '<example>\nfoo\n</example>', '<example>\nfoo\n</example>'],
        ['a tag in a list item', '- keep <example>', 'keep <example>'],
        ['a tag in a blockquote', '> keep <example>', 'keep <example>'],
        ['a tag in inline code', 'use `<example>` here', 'use <example> here'],
        ['indented code', '    <example>', '<example>'],
        ['a fence in a list item', '- ```\n  <example>\n  ```', '<example>'],
        ['inline code over two lines', '`a\n<example>`', 'a\n<example>'],
        ['an autolink', 'see <https://example.com/a?b=1>', 'see https://example.com/a?b=1'],
        ['an escaped tag', 'a \\<example>', 'a <example>'],
    ])('shows %s as typed', (_, markdown, expected) => {
        expect(visibleText(literalTree(markdown))).toBe(expected)
    })

    it('puts a tag block in a paragraph', () => {
        expect(literalTree('<example>\nfoo').children?.map((node) => node.type)).toEqual(['paragraph'])
    })

    it.each(XSS_PAYLOADS)('leaves no raw HTML node from %s', (_, payload) => {
        for (const prefix of ['', 'Hello ', '> ', '- ', '**bold** ', '`code` ']) {
            const htmlNodes = nodes(literalTree(`${prefix}${payload}`)).filter((node) => node.type === 'html')
            expect({ prefix, htmlNodes }).toEqual({ prefix, htmlNodes: [] })
        }
    })
})
