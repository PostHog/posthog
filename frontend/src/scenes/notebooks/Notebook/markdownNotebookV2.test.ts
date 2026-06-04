import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../types'
import {
    appendMarkdownNotebookBlock,
    buildMarkdownNotebookContent,
    convertNotebookContentToMarkdown,
    getMarkdownNotebookMarkdown,
    isMarkdownNotebookContent,
} from './markdownNotebookV2'

describe('markdownNotebookV2', () => {
    it('stores v2 notebooks as a single markdown notebook node', () => {
        const content = buildMarkdownNotebookContent('# Activation')

        expect(content).toEqual({
            type: 'doc',
            content: [
                {
                    type: NotebookNodeType.MarkdownNotebook,
                    attrs: {
                        nodeId: 'markdown-notebook-v2',
                        markdown: '# Activation',
                    },
                },
            ],
        })
        expect(isMarkdownNotebookContent(content)).toBe(true)
        expect(getMarkdownNotebookMarkdown(content)).toEqual('# Activation')
    })

    it('appends markdown blocks to v2 notebook content', () => {
        const content = buildMarkdownNotebookContent('# Activation')
        const nextContent = appendMarkdownNotebookBlock(
            content,
            '<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />'
        )

        expect(getMarkdownNotebookMarkdown(nextContent)).toEqual(`# Activation

<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />`)
    })

    it('converts common legacy notebook nodes to markdown', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'heading',
                    attrs: { level: 1 },
                    content: [{ type: 'text', text: 'Activation' }],
                },
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'A ' },
                        { type: 'text', text: 'bold', marks: [{ type: 'bold' }] },
                        { type: 'text', text: ' paragraph.' },
                    ],
                },
                {
                    type: NotebookNodeType.Query,
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: { kind: 'FunnelsQuery', series: [] },
                        },
                    },
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(`# Activation

A **bold** paragraph.

<Query query={{"kind":"InsightVizNode","source":{"kind":"FunnelsQuery","series":[]}}} />`)
    })
})
