import { notebookContentToMarkdown, notebookNodeToMarkdown } from './markdown'
import { NotebookNodeType } from './types'

describe('notebook markdown', () => {
    it('serializes query nodes to Query tags', () => {
        expect(
            notebookNodeToMarkdown(NotebookNodeType.Query, {
                title: 'Weekly signups',
                query: {
                    kind: 'InsightVizNode',
                    source: { kind: 'TrendsQuery', series: [] },
                },
            })
        ).toContain('<Query title="Weekly signups">')
    })

    it('serializes resource nodes to compact tags', () => {
        expect(notebookNodeToMarkdown(NotebookNodeType.FeatureFlag, { id: 12 })).toBe('<FeatureFlag id="12" />')
        expect(notebookNodeToMarkdown(NotebookNodeType.Recording, { id: 'session-1' })).toBe(
            '<SessionReplay id="session-1" />'
        )
    })

    it('serializes a mixed notebook document', () => {
        const markdown = notebookContentToMarkdown({
            type: 'doc',
            content: [
                {
                    type: 'heading',
                    attrs: { level: 1 },
                    content: [{ type: 'text', text: 'Report' }],
                },
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'Markdown backed.' }],
                },
                {
                    type: NotebookNodeType.DuckSQL,
                    attrs: { code: 'select 1', returnVariable: 'rows' },
                },
            ],
        })

        expect(markdown).toContain('# Report')
        expect(markdown).toContain('Markdown backed.')
        expect(markdown).toContain('<DuckSQL return_variable="rows">')
    })

    it('uses Tiptap markdown serialization for standard editor nodes', () => {
        const markdown = notebookContentToMarkdown({
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'Read ' },
                        {
                            type: 'text',
                            text: 'the docs',
                            marks: [{ type: 'link', attrs: { href: 'https://posthog.com/docs' } }],
                        },
                    ],
                },
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'one' }] }],
                        },
                    ],
                },
            ],
        })

        expect(markdown).toContain('[the docs](https://posthog.com/docs)')
        expect(markdown).toContain('- one')
    })
})
