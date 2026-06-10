import { JSONContent } from 'lib/components/RichContentEditor/types'

import { ArtifactContentType, NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'

import { NotebookNodeType } from '../types'
import {
    appendMarkdownNotebookBlock,
    buildMarkdownNotebookContent,
    convertNotebookContentToMarkdown,
    getMarkdownNotebookMarkdown,
    isMarkdownNotebookContent,
    notebookArtifactContentToMarkdown,
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
                {
                    type: NotebookNodeType.Image,
                    attrs: {
                        src: 'https://res.cloudinary.com/demo/image/upload/posthog.png',
                        alt: 'PostHog engineering',
                    },
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(`# Activation

A **bold** paragraph.

<Query query={{"kind":"InsightVizNode","source":{"kind":"FunnelsQuery","series":[]}}} />

![PostHog engineering](https://res.cloudinary.com/demo/image/upload/posthog.png)`)
    })

    it('converts notebook artifacts to markdown notebook content', () => {
        const content: NotebookArtifactContent = {
            content_type: ArtifactContentType.Notebook,
            title: 'Activation summary',
            blocks: [
                { type: 'markdown', content: 'Users activated faster.' },
                {
                    type: 'visualization',
                    title: 'Activation trend',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [],
                    },
                },
                {
                    type: 'session_replay',
                    session_id: '018a8a51-a39d-7b18-897f-94054eec5f61',
                    timestamp_ms: 12000,
                    title: 'Activation replay',
                },
            ],
        }

        expect(notebookArtifactContentToMarkdown(content)).toEqual(`# Activation summary

Users activated faster.

<Query query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]},"showHeader":true}} title="Activation trend" />

<Recording id="018a8a51-a39d-7b18-897f-94054eec5f61" timestampMs={12000} title="Activation replay" />`)
    })

    it('does not duplicate an artifact markdown title', () => {
        const content: NotebookArtifactContent = {
            content_type: ArtifactContentType.Notebook,
            title: 'Activation summary',
            blocks: [{ type: 'markdown', content: '# Existing title\n\nBody' }],
        }

        expect(notebookArtifactContentToMarkdown(content)).toEqual(`# Existing title

Body`)
    })
})
