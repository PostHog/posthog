import {
    ensureEditableNotebookDocument,
    getMarkdownNotebookVisualGroups,
    removeNotebookNodesWithRefCleanup,
} from './documentModel'
import { removeInlineRefMark, setInlineRefMark } from './inlineContent'
import { parseMarkdownNotebook, serializeMarkdownNotebook } from './markdown'
import { NotebookDocument } from './types'

describe('discussion comments', () => {
    const parse = (markdown: string): NotebookDocument => parseMarkdownNotebook(markdown)

    describe('setInlineRefMark', () => {
        it('wraps the selected range in a ref mark', () => {
            const children = setInlineRefMark(
                [{ type: 'text', text: 'Numbers look off here' }],
                { nodeId: 'n', start: 8, end: 12 },
                'banana'
            )

            expect(children).toEqual([
                { type: 'text', text: 'Numbers ' },
                { type: 'text', text: 'look', marks: [{ type: 'ref', id: 'banana' }] },
                { type: 'text', text: ' off here' },
            ])
        })

        it('replaces an existing ref on the selected range', () => {
            const children = setInlineRefMark(
                [{ type: 'text', text: 'word', marks: [{ type: 'ref', id: 'old' }] }],
                { nodeId: 'n', start: 0, end: 4 },
                'new'
            )

            expect(children).toEqual([{ type: 'text', text: 'word', marks: [{ type: 'ref', id: 'new' }] }])
        })
    })

    describe('removeInlineRefMark', () => {
        it('removes only the matching ref and keeps the text', () => {
            const children = removeInlineRefMark(
                [
                    { type: 'text', text: 'one', marks: [{ type: 'ref', id: 'a' }] },
                    { type: 'text', text: 'two', marks: [{ type: 'ref', id: 'b' }] },
                ],
                'a'
            )

            expect(children).toEqual([
                { type: 'text', text: 'one' },
                { type: 'text', text: 'two', marks: [{ type: 'ref', id: 'b' }] },
            ])
        })

        it('keeps other marks on the unwrapped text', () => {
            const children = removeInlineRefMark(
                [{ type: 'text', text: 'bold', marks: [{ type: 'bold' }, { type: 'ref', id: 'a' }] }],
                'a'
            )

            expect(children).toEqual([{ type: 'text', text: 'bold', marks: [{ type: 'bold' }] }])
        })
    })

    describe('getMarkdownNotebookVisualGroups', () => {
        it('keeps a comment thread inside the surrounding text group instead of splitting it', () => {
            const document = parse(
                [
                    'Paragraph one',
                    '',
                    '<Comment ref="x" replies={[]} />',
                    '',
                    'Paragraph <ref id="x">two</ref>',
                    '',
                    'Paragraph three',
                ].join('\n')
            )

            const groups = getMarkdownNotebookVisualGroups(document.nodes)

            expect(groups).toHaveLength(1)
            expect(groups[0].type).toEqual('text')
            expect(groups[0].type === 'text' ? groups[0].items.map((item) => item.surface) : []).toEqual([
                'text',
                'comment',
                'text',
                'text',
            ])
        })

        it('keeps a comment anchored to a standalone component as its own row', () => {
            const document = parse(
                ['<Comment ref="q" replies={[]} />', '', '<Query query={{"kind":"DataTableNode"}} />'].join('\n')
            )

            const groups = getMarkdownNotebookVisualGroups(document.nodes)

            expect(groups.map((group) => group.type)).toEqual(['block', 'block'])
        })
    })

    describe('ensureEditableNotebookDocument', () => {
        it('slides a leading comment thread below the title instead of adding an empty title', () => {
            const document = parse(
                ['<Comment ref="x" replies={[]} />', '', '# <ref id="x">Title</ref>', '', 'Body'].join('\n')
            )

            const result = ensureEditableNotebookDocument(document)

            expect(result.nodes.map((node) => node.type)).toEqual(['heading', 'component', 'paragraph'])
            expect(serializeMarkdownNotebook(result)).toEqual(
                '# <ref id="x">Title</ref>\n\n<Comment ref="x" replies={[]} />\n\nBody'
            )
        })
    })

    describe('removeNotebookNodesWithRefCleanup', () => {
        const markdown = [
            '# Title',
            '',
            'Numbers <ref id="banana">look off</ref> here',
            '',
            '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"Why?"}]} />',
        ].join('\n')

        it('deleting the comment thread also unwraps its ref highlight', () => {
            const document = parse(markdown)
            const commentNode = document.nodes.find((node) => node.type === 'component')

            const result = removeNotebookNodesWithRefCleanup(document, new Set([commentNode!.id]))

            expect(serializeMarkdownNotebook(result)).toEqual('# Title\n\nNumbers look off here')
        })

        it('deleting the paragraph holding the ref keeps the comment thread', () => {
            const document = parse(markdown)
            const paragraphNode = document.nodes.find((node) => node.type === 'paragraph')

            const result = removeNotebookNodesWithRefCleanup(document, new Set([paragraphNode!.id]))
            const serialized = serializeMarkdownNotebook(result)

            expect(serialized).toContain('<Comment ref="banana"')
            expect(serialized).not.toContain('look off')
        })

        it('unwraps refs inside list items and table cells', () => {
            const document = parse(
                [
                    '- item <ref id="x">marked</ref>',
                    '',
                    '| a <ref id="x">b</ref> |',
                    '| --- |',
                    '| c |',
                    '',
                    '<Comment ref="x" replies={[]} />',
                ].join('\n')
            )
            const commentNode = document.nodes.find((node) => node.type === 'component')

            const result = removeNotebookNodesWithRefCleanup(document, new Set([commentNode!.id]))
            const serialized = serializeMarkdownNotebook(result)

            expect(serialized).not.toContain('<ref')
            expect(serialized).toContain('item marked')
        })

        it('deleting a non-comment node leaves unrelated refs alone', () => {
            const document = parse(markdown)
            const titleNode = document.nodes[0]

            const result = removeNotebookNodesWithRefCleanup(document, new Set([titleNode.id]))

            expect(serializeMarkdownNotebook(result)).toContain('<ref id="banana">look off</ref>')
        })
    })
})
