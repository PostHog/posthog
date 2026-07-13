import { parseMarkdownNotebook, serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../types'
import { convertMarkdownToNotebookContent } from './markdownNotebookDowngrade'
import { convertNotebookContentToMarkdown } from './markdownNotebookV2'

describe('markdownNotebookDowngrade', () => {
    it('returns an empty doc for empty markdown', () => {
        expect(convertMarkdownToNotebookContent('')).toEqual({ type: 'doc', content: [] })
    })

    it('converts paragraphs with hard breaks', () => {
        expect(convertMarkdownToNotebookContent('First line\nSecond line')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'First line' },
                        { type: 'hardBreak' },
                        { type: 'text', text: 'Second line' },
                    ],
                },
            ],
        })
    })

    it.each([[1], [2], [3], [4], [5], [6]])('converts level %i headings', (level) => {
        expect(convertMarkdownToNotebookContent(`${'#'.repeat(level)} Title`)).toEqual({
            type: 'doc',
            content: [{ type: 'heading', attrs: { level }, content: [{ type: 'text', text: 'Title' }] }],
        })
    })

    it('converts blockquotes to a blockquote with a paragraph child', () => {
        expect(convertMarkdownToNotebookContent('> Quoted text')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'blockquote',
                    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Quoted text' }] }],
                },
            ],
        })
    })

    it.each<[string, string, JSONContentMarks]>([
        ['**bold**', 'bold', [{ type: 'bold' }]],
        ['*italic*', 'italic', [{ type: 'italic' }]],
        ['<u>underline</u>', 'underline', [{ type: 'underline' }]],
        ['~~strike~~', 'strike', [{ type: 'strike' }]],
        ['`code`', 'code', [{ type: 'code' }]],
        ['[label](https://posthog.com)', 'label', [{ type: 'link', attrs: { href: 'https://posthog.com' } }]],
        ['<ref id="thread-1">anchored</ref>', 'anchored', [{ type: 'comment', attrs: { id: 'thread-1' } }]],
    ])('converts inline %s to a marked text node', (markdown, text, marks) => {
        expect(convertMarkdownToNotebookContent(markdown)).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text, marks }] }],
        })
    })

    it('converts mention marks to atomic v1 mention nodes, replacing the label', () => {
        expect(convertMarkdownToNotebookContent('Ping <mention id="5">@Marius</mention> please')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'Ping ' },
                        { type: NotebookNodeType.Mention, attrs: { id: 5 } },
                        { type: 'text', text: ' please' },
                    ],
                },
            ],
        })
    })

    it('keeps the label as plain text when a mention id is not numeric', () => {
        expect(convertMarkdownToNotebookContent('<mention id="abc">@Someone</mention>')).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: '@Someone' }] }],
        })
    })

    it('collapses a partially formatted mention label into a single mention node', () => {
        expect(convertMarkdownToNotebookContent('<mention id="7">@**M**ember</mention>')).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: NotebookNodeType.Mention, attrs: { id: 7 } }] }],
        })
    })

    it('reconstructs nested bullet lists from item depth', () => {
        expect(convertMarkdownToNotebookContent('- One\n- Two\n  - Nested\n- Three')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'bulletList',
                    content: [
                        listItem('One'),
                        {
                            type: 'listItem',
                            content: [
                                { type: 'paragraph', content: [{ type: 'text', text: 'Two' }] },
                                { type: 'bulletList', content: [listItem('Nested')] },
                            ],
                        },
                        listItem('Three'),
                    ],
                },
            ],
        })
    })

    it('converts ordered lists and keeps a non-default start', () => {
        expect(convertMarkdownToNotebookContent('3. Third\n4. Fourth')).toEqual({
            type: 'doc',
            content: [{ type: 'orderedList', attrs: { start: 3 }, content: [listItem('Third'), listItem('Fourth')] }],
        })
    })

    it('nests an ordered sub-list inside a bullet list item', () => {
        expect(convertMarkdownToNotebookContent('- Parent\n  1. Child')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [
                                { type: 'paragraph', content: [{ type: 'text', text: 'Parent' }] },
                                { type: 'orderedList', content: [listItem('Child')] },
                            ],
                        },
                    ],
                },
            ],
        })
    })

    it('converts task lists to taskList with checked taskItems, nesting by depth', () => {
        expect(convertMarkdownToNotebookContent('- [x] Done\n- [ ] Open\n  - [ ] Nested open')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'taskList',
                    content: [
                        {
                            type: 'taskItem',
                            attrs: { checked: true },
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Done' }] }],
                        },
                        {
                            type: 'taskItem',
                            attrs: { checked: false },
                            content: [
                                { type: 'paragraph', content: [{ type: 'text', text: 'Open' }] },
                                {
                                    type: 'taskList',
                                    content: [
                                        {
                                            type: 'taskItem',
                                            attrs: { checked: false },
                                            content: [
                                                {
                                                    type: 'paragraph',
                                                    content: [{ type: 'text', text: 'Nested open' }],
                                                },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        })
    })

    it('splits a plain item after a task run into a sibling bulletList', () => {
        expect(convertMarkdownToNotebookContent('- [x] Task\n- Plain')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'taskList',
                    content: [
                        {
                            type: 'taskItem',
                            attrs: { checked: true },
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Task' }] }],
                        },
                    ],
                },
                { type: 'bulletList', content: [listItem('Plain')] },
            ],
        })
    })

    it('keeps the checked state of a task item that follows a plain item by splitting into a sibling taskList', () => {
        expect(convertMarkdownToNotebookContent('- plain\n- [x] done')).toEqual({
            type: 'doc',
            content: [
                { type: 'bulletList', content: [listItem('plain')] },
                {
                    type: 'taskList',
                    content: [
                        {
                            type: 'taskItem',
                            attrs: { checked: true },
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'done' }] }],
                        },
                    ],
                },
            ],
        })
    })

    it('splits a nested task run inside a plain list into a nested taskList without losing checked state', () => {
        expect(convertMarkdownToNotebookContent('- Parent\n  - [ ] Child task\n  - Plain child')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [
                                { type: 'paragraph', content: [{ type: 'text', text: 'Parent' }] },
                                {
                                    type: 'taskList',
                                    content: [
                                        {
                                            type: 'taskItem',
                                            attrs: { checked: false },
                                            content: [
                                                {
                                                    type: 'paragraph',
                                                    content: [{ type: 'text', text: 'Child task' }],
                                                },
                                            ],
                                        },
                                    ],
                                },
                                { type: 'bulletList', content: [listItem('Plain child')] },
                            ],
                        },
                    ],
                },
            ],
        })
    })

    it('wraps blockquoted lists in a blockquote', () => {
        expect(convertMarkdownToNotebookContent('> - One\n> - Two')).toEqual({
            type: 'doc',
            content: [
                { type: 'blockquote', content: [{ type: 'bulletList', content: [listItem('One'), listItem('Two')] }] },
            ],
        })
    })

    it('converts code blocks to codeBlock with a single text child', () => {
        expect(convertMarkdownToNotebookContent('```python\nprint("hi")\nprint("bye")\n```')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'codeBlock',
                    attrs: { language: 'python' },
                    content: [{ type: 'text', text: 'print("hi")\nprint("bye")' }],
                },
            ],
        })
    })

    it('converts empty code blocks without a language', () => {
        expect(convertMarkdownToNotebookContent('```\n```')).toEqual({
            type: 'doc',
            content: [{ type: 'codeBlock', attrs: { language: null } }],
        })
    })

    it('converts tables to TipTap table structure with paragraph-wrapped cells', () => {
        expect(convertMarkdownToNotebookContent('| Name | Value |\n| --- | --- |\n| Users | **42** |')).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'table',
                    content: [
                        {
                            type: 'tableRow',
                            content: [tableCell('tableHeader', 'Name'), tableCell('tableHeader', 'Value')],
                        },
                        {
                            type: 'tableRow',
                            content: [
                                tableCell('tableCell', 'Users'),
                                {
                                    type: 'tableCell',
                                    content: [
                                        {
                                            type: 'paragraph',
                                            content: [{ type: 'text', text: '42', marks: [{ type: 'bold' }] }],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        })
    })

    it('converts dividers to horizontalRule', () => {
        expect(convertMarkdownToNotebookContent('---')).toEqual({
            type: 'doc',
            content: [{ type: 'horizontalRule' }],
        })
    })

    it('converts images to the v1 image node', () => {
        expect(convertMarkdownToNotebookContent('![PostHog](https://example.com/hog.png)')).toEqual({
            type: 'doc',
            content: [{ type: NotebookNodeType.Image, attrs: { src: 'https://example.com/hog.png', alt: 'PostHog' } }],
        })
    })

    it('converts component tags to their v1 node type with props as attrs', () => {
        expect(convertMarkdownToNotebookContent('<Query query={{"kind":"DataTableNode"}} />')).toEqual({
            type: 'doc',
            content: [{ type: NotebookNodeType.Query, attrs: { query: { kind: 'DataTableNode' }, edit: true } }],
        })
    })

    it.each<[string, NotebookNodeType]>([
        ['<Recording id="abc" />', NotebookNodeType.Recording],
        ['<FeatureFlag id={42} />', NotebookNodeType.FeatureFlag],
        ['<Survey id="s1" />', NotebookNodeType.Survey],
        ['<Embed src="https://example.com" />', NotebookNodeType.Embed],
    ])('converts %s to its v1 node type', (markdown, nodeType) => {
        expect(convertMarkdownToNotebookContent(markdown).content?.[0]?.type).toEqual(nodeType)
    })

    it('converts authorial comments to plain paragraphs', () => {
        expect(convertMarkdownToNotebookContent('<!-- A note to self -->')).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'A note to self' }] }],
        })
    })

    it('drops discussion comment threads but keeps the ref anchor as a comment mark', () => {
        expect(
            convertMarkdownToNotebookContent(
                '<ref id="t1">anchored</ref>\n\n<Comment ref="t1" replies={[{"text":"hi"}]} />'
            )
        ).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'anchored', marks: [{ type: 'comment', attrs: { id: 't1' } }] }],
                },
            ],
        })
    })

    it('drops Prompt blocks', () => {
        const markdown = '<Prompt text="hello" />'

        expect(convertMarkdownToNotebookContent(markdown)).toEqual({ type: 'doc', content: [] })
    })

    it('re-emits UnknownNode wrappers as their original node type', () => {
        expect(convertMarkdownToNotebookContent('<UnknownNode nodeType="ph-custom" foo="bar" />')).toEqual({
            type: 'doc',
            content: [{ type: 'ph-custom', attrs: { foo: 'bar' } }],
        })
    })

    it('falls back to a paragraph with the serialized source for unmapped tags', () => {
        expect(convertMarkdownToNotebookContent('<Mystery foo="bar" />')).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: '<Mystery foo="bar" />' }] }],
        })
    })

    it('round-trips a representative lossless document through v1 and back', () => {
        const markdown = [
            '# Roadmap',
            'A **bold**, *italic*, <u>underlined</u>, ~~struck~~, `coded`, [linked](https://posthog.com) line.',
            'Multi\nline paragraph',
            '<Comment ref="thread-1" replies={[]} />',
            '<ref id="thread-1">Highlighted decision</ref> needs review.',
            'Ping <mention id="5">@member</mention> about this.',
            '> A wise quote',
            '- First bullet\n- Second bullet\n  - Nested bullet',
            '1. Step one\n2. Step two',
            '> - Quoted item one\n> - Quoted item two',
            '| Metric | Value |\n| --- | --- |\n| Users | **42** |',
            '```python\nprint("hello")\n```',
            '---',
            '<Query query={{"kind":"DataTableNode"}} />',
            '<UnknownNode nodeType="ph-custom" foo="bar" />',
            '![Dashboard](https://example.com/dashboard.png)',
        ].join('\n\n')

        const roundTrippedMarkdown = convertNotebookContentToMarkdown(convertMarkdownToNotebookContent(markdown))

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(roundTrippedMarkdown))).toEqual(
            serializeMarkdownNotebook(parseMarkdownNotebook(markdown))
        )
    })

    it('keeps discussion anchors but loses thread replies on round-trip', () => {
        const markdown = [
            '<ref id="t1">anchored</ref>',
            '<Comment ref="t1" replies={[{"author":"Ann","text":"hi"}]} />',
        ].join('\n\n')

        expect(convertNotebookContentToMarkdown(convertMarkdownToNotebookContent(markdown))).toEqual(
            '<Comment ref="t1" replies={[]} />\n\n<ref id="t1">anchored</ref>'
        )
    })
})

type JSONContentMarks = NonNullable<JSONContent['marks']>

function listItem(text: string): JSONContent {
    return { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] }
}

function tableCell(type: 'tableHeader' | 'tableCell', text: string): JSONContent {
    return { type, content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] }
}
