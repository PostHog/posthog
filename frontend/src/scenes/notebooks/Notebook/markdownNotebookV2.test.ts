import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import {
    ArtifactContentType,
    NotebookArtifactContent,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'

import { NotebookNodeType } from '../types'
import {
    appendMarkdownNotebookBlock,
    buildMarkdownNotebookContent,
    convertDroppedPostHogUrlToMarkdownNode,
    convertDroppedRichContentNodeToMarkdownNode,
    convertNotebookContentToMarkdown,
    getMarkdownNotebookMarkdown,
    getMarkdownNotebookTitle,
    isMarkdownNotebookContent,
    notebookArtifactContentToMarkdown,
    notebookContentHasCommentMarks,
    visualizationArtifactContentToNotebookArtifactContent,
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

    it('extracts the title from the first level-1 heading, ignoring code blocks', () => {
        const content = buildMarkdownNotebookContent('```sh\n# not the title\n```\n\n# Real title\n\nbody')

        expect(getMarkdownNotebookTitle(content)).toEqual('Real title')
        expect(getMarkdownNotebookTitle(buildMarkdownNotebookContent('just a paragraph'))).toBeNull()
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
                    type: NotebookNodeType.Recording,
                    attrs: {
                        id: '018b4205-f670-7fa8-928a-040abaaf596d',
                        title: 'Session replay',
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

<Query hideFilters query={{"kind":"InsightVizNode","source":{"kind":"FunnelsQuery","series":[]}}} />

<Recording hideFilters id="018b4205-f670-7fa8-928a-040abaaf596d" title="Session replay" />

![PostHog engineering](https://res.cloudinary.com/demo/image/upload/posthog.png)`)
    })

    it('preserves explicitly open legacy widget filters', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: NotebookNodeType.Query,
                    attrs: {
                        query: {
                            kind: 'SavedInsightNode',
                            shortId: 'open',
                        },
                        edit: true,
                    },
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(
            '<Query query={{"kind":"SavedInsightNode","shortId":"open"}} />'
        )
    })

    it('converts raw legacy content arrays without dropping top-level text nodes', () => {
        const content: JSONContent[] = [
            {
                type: 'heading',
                attrs: { level: 1 },
                content: [{ type: 'text', text: 'Array notebook' }],
            },
            { type: 'text', text: 'Loose top-level text', marks: [{ type: 'italic' }] },
            { type: 'paragraph', content: [{ type: 'text', text: 'Wrapped paragraph' }] },
        ]

        expect(convertNotebookContentToMarkdown(content)).toEqual(`# Array notebook

*Loose top-level text*

Wrapped paragraph`)
    })

    it('converts string content without dropping data', () => {
        const legacyDocString = JSON.stringify({
            type: 'doc',
            content: [
                {
                    type: 'heading',
                    attrs: { level: 1 },
                    content: [{ type: 'text', text: 'JSON string notebook' }],
                },
            ],
        })

        expect(convertNotebookContentToMarkdown(legacyDocString)).toEqual('# JSON string notebook')
        expect(convertNotebookContentToMarkdown('# Already Markdown\n\nPlain body')).toEqual(
            '# Already Markdown\n\nPlain body'
        )
        expect(convertNotebookContentToMarkdown('Plain text body')).toEqual('Plain text body')
    })

    it('converts legacy ph-insight nodes to saved insight query tags', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                { type: 'ph-insight', attrs: { id: 'abc123' } },
                { type: 'ph-insight', attrs: { id: 123, short_id: 'def456' } },
            ],
        }

        expect(convertNotebookContentToMarkdown(content))
            .toEqual(`<Query hideFilters query={{"kind":"SavedInsightNode","shortId":"abc123"}} />

<Query hideFilters query={{"kind":"SavedInsightNode","shortId":"def456"}} />`)
    })

    it('converts remaining legacy production node shapes without unknown nodes', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                { type: 'ph-text', attrs: { body: '# Markdown body' } },
                { type: 'ph-dashboard', attrs: { id: 123 } },
                {
                    type: 'query',
                    attrs: {
                        query: {
                            kind: 'HogQLQuery',
                            query: 'select event from events limit 1',
                        },
                    },
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(`# Markdown body

Dashboard 123

<Query hideFilters query={{"kind":"DataVisualizationNode","source":{"kind":"HogQLQuery","query":"select event from events limit 1"}}} />`)
    })

    it('keeps the stable id vector for markdown query blocks without nodeId props', () => {
        const markdown =
            '<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery","select":["event"],"after":"-24h","limit":1}}} />'

        expect(parseMarkdownNotebook(markdown).nodes[0]?.id).toEqual('mdn-197jp5a-0')
    })

    it('keeps a query attr whose object carries nested undefined optional fields', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: NotebookNodeType.Query,
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [{ kind: 'EventsNode', event: '$pageview', math: undefined }],
                                properties: undefined,
                            },
                            full: undefined,
                        },
                        isDefaultFilterApplied: false,
                    },
                },
            ],
        }

        // Nested undefined must be stripped, not cause the whole query prop to be dropped.
        expect(convertNotebookContentToMarkdown(content)).toEqual(
            '<Query hideFilters query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[{"kind":"EventsNode","event":"$pageview"}]}}} isDefaultFilterApplied={false} />'
        )
    })

    it('serializes a json-string query attr as an expression that parses back to an object', () => {
        // Persisted v1 nodes can carry `query` as a JSON string (NodeWrapper round-trips attrs as
        // JSON). Serializing it verbatim emits query="..." which parses back as a string, rendering
        // an empty Query node.
        const queryObject = {
            kind: 'DataVisualizationNode',
            source: { kind: 'HogQLQuery', query: 'select event, count() from events group by event' },
            display: 'ActionsTable',
        }
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: NotebookNodeType.Query,
                    attrs: { query: JSON.stringify(queryObject), nodeId: 'cc41998d' },
                },
            ],
        }

        const markdown = convertNotebookContentToMarkdown(content)
        expect(markdown).toContain('query={{"kind":"DataVisualizationNode"')
        expect(markdown).not.toContain('query="')

        const parsedNode = parseMarkdownNotebook(markdown).nodes.find((node) => node.type === 'component')
        expect(parsedNode?.type === 'component' ? parsedNode.props.query : null).toEqual(queryObject)
    })

    it('converts legacy task lists to checkbox list markdown', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'taskList',
                    content: [
                        {
                            type: 'taskItem',
                            attrs: { checked: true },
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Done thing' }] }],
                        },
                        {
                            type: 'taskItem',
                            attrs: { checked: false },
                            content: [
                                { type: 'paragraph', content: [{ type: 'text', text: 'Open thing' }] },
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
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(`- [x] Done thing
- [ ] Open thing
  - [ ] Nested open`)
    })

    it('keeps extra block content from legacy list items instead of dropping it', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [
                                { type: 'paragraph', content: [{ type: 'text', text: 'first para' }] },
                                { type: 'paragraph', content: [{ type: 'text', text: 'second para' }] },
                                {
                                    type: 'codeBlock',
                                    attrs: { language: 'sql' },
                                    content: [{ type: 'text', text: 'select 1' }],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'next item' }] }],
                        },
                    ],
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(`- first para

second para

\`\`\`sql
select 1
\`\`\`

- next item`)
    })

    it('converts horizontal rules and strikethrough marks', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                { type: 'paragraph', content: [{ type: 'text', text: 'struck', marks: [{ type: 'strike' }] }] },
                { type: 'horizontalRule' },
                { type: 'paragraph', content: [{ type: 'text', text: 'after' }] },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(`~~struck~~

---

after`)
    })

    it('flattens hard breaks inside table cells so rows stay on one line', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'table',
                    content: [
                        {
                            type: 'tableRow',
                            content: [
                                {
                                    type: 'tableHeader',
                                    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'H1' }] }],
                                },
                            ],
                        },
                        {
                            type: 'tableRow',
                            content: [
                                {
                                    type: 'tableCell',
                                    content: [
                                        {
                                            type: 'paragraph',
                                            content: [
                                                { type: 'text', text: 'line1' },
                                                { type: 'hardBreak' },
                                                { type: 'text', text: 'line2' },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(`| H1 |
| --- |
| line1 line2 |`)
    })

    it('converts legacy markdown ast alias nodes without losing structure', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'bullet_list',
                    content: [
                        {
                            type: 'list_item',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'first' }] }],
                        },
                    ],
                },
                {
                    type: 'ordered_list',
                    content: [
                        {
                            type: 'list_item',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'step' }] }],
                        },
                    ],
                },
                {
                    type: 'code_block',
                    attrs: { language: 'sql' },
                    content: [
                        { type: 'text', text: 'select 1' },
                        { type: 'hardBreak' },
                        { type: 'text', text: 'select 2' },
                    ],
                },
                {
                    type: 'table',
                    content: [
                        {
                            type: 'table_row',
                            content: [
                                {
                                    type: 'table_header',
                                    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Metric' }] }],
                                },
                                {
                                    type: 'table_cell',
                                    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Value' }] }],
                                },
                            ],
                        },
                    ],
                },
                {
                    type: 'callout',
                    attrs: { emoji: '!' },
                    content: [
                        {
                            type: 'paragraph',
                            content: [
                                { type: 'text', text: 'Heads', marks: [{ type: 'strong' }] },
                                { type: 'text', text: ' and ' },
                                { type: 'text', text: 'note', marks: [{ type: 'em' }] },
                            ],
                        },
                    ],
                },
                { type: 'ph-link', attrs: { href: 'https://app.posthog.com/cohorts/37958' } },
            ],
        }

        const markdown = convertNotebookContentToMarkdown(content)

        expect(markdown).toContain('- first')
        expect(markdown).toContain('1. step')
        expect(markdown).toContain('```sql\nselect 1\nselect 2\n```')
        expect(markdown).toContain('| Metric | Value |')
        expect(markdown).toContain('| --- | --- |')
        expect(markdown).toContain('> ! **Heads** and *note*')
        expect(markdown).toContain('[https://app.posthog.com/cohorts/37958](https://app.posthog.com/cohorts/37958)')
        expect(parseMarkdownNotebook(markdown).errors).toEqual([])
    })

    it('produces markdown that parses without errors in the markdown notebook model', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Mixed' }] },
                {
                    type: 'taskList',
                    content: [
                        {
                            type: 'taskItem',
                            attrs: { checked: true },
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'task' }] }],
                        },
                    ],
                },
                { type: 'horizontalRule' },
                {
                    type: 'blockquote',
                    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'quote' }] }],
                },
            ],
        }

        const parsed = parseMarkdownNotebook(convertNotebookContentToMarkdown(content))
        expect(parsed.errors).toEqual([])
        // The legacy horizontal rule round-trips into the markdown notebook divider component
        expect(parsed.nodes.map((node) => node.type)).toEqual(['heading', 'list', 'component', 'blockquote'])
    })

    it('splits embedded cards out of blockquotes while keeping headings quoted', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'blockquote',
                    content: [
                        { type: 'paragraph', content: [{ type: 'text', text: 'Quoted context' }] },
                        {
                            type: NotebookNodeType.Query,
                            attrs: {
                                query: { kind: NodeKind.SavedInsightNode, shortId: 'abc123' },
                                hideFilters: true,
                            },
                        },
                        {
                            type: 'blockquote',
                            content: [
                                {
                                    type: 'heading',
                                    attrs: { level: 2 },
                                    content: [{ type: 'text', text: 'Where to improve' }],
                                },
                                { type: NotebookNodeType.Python, attrs: { code: 'print(1)', hideFilters: true } },
                            ],
                        },
                    ],
                },
            ],
        }

        const markdown = convertNotebookContentToMarkdown(content)

        expect(markdown).toContain('> Quoted context')
        expect(markdown).toContain('\n\n<Query ')
        expect(markdown).toContain('> ## Where to improve')
        expect(markdown).toContain('\n\n<Python ')
        expect(markdown).not.toContain('> <')

        const parsed = parseMarkdownNotebook(markdown)
        expect(parsed.errors).toEqual([])
        expect(parsed.nodes.flatMap((node) => (node.type === 'component' ? [node.tagName] : []))).toEqual([
            'Query',
            'Python',
        ])
        const quotedHeading = parsed.nodes.find((node) => node.type === 'heading')
        expect(quotedHeading?.type === 'heading' && quotedHeading.blockquote).toBe(true)
    })

    it('splits embedded cards out of callouts while keeping the emoji and text quoted', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'callout',
                    attrs: { emoji: '!' },
                    content: [
                        { type: 'paragraph', content: [{ type: 'text', text: 'Watch this' }] },
                        {
                            type: NotebookNodeType.Query,
                            attrs: {
                                query: { kind: NodeKind.SavedInsightNode, shortId: 'abc123' },
                                hideFilters: true,
                            },
                        },
                    ],
                },
            ],
        }

        const markdown = convertNotebookContentToMarkdown(content)

        expect(markdown).toContain('> ! Watch this')
        expect(markdown).toContain('\n\n<Query ')
        expect(markdown).not.toContain('> <')
        expect(parseMarkdownNotebook(markdown).errors).toEqual([])
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

<Query hideFilters query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]},"showHeader":true}} title="Activation trend" />

<Recording id="018a8a51-a39d-7b18-897f-94054eec5f61" timestampMs={12000} title="Activation replay" />`)
    })

    it('preserves SQL pie chart display intent from notebook artifacts', () => {
        const content: NotebookArtifactContent = {
            content_type: ArtifactContentType.Notebook,
            blocks: [
                {
                    type: 'visualization',
                    title: 'Events pie chart',
                    query: {
                        kind: NodeKind.HogQLQuery,
                        query: 'select event, count() from events group by event',
                    },
                },
            ],
        }

        expect(notebookArtifactContentToMarkdown(content)).toEqual(
            '<Query hideFilters query={{"kind":"DataVisualizationNode","source":{"kind":"HogQLQuery","query":"select event, count() from events group by event"},"display":"ActionsPie"}} title="Events pie chart" />'
        )
    })

    it('converts visualization artifacts to notebook query content', () => {
        const content: VisualizationArtifactContent = {
            content_type: ArtifactContentType.Visualization,
            plan: 'Create a pie chart',
            query: {
                kind: NodeKind.HogQLQuery,
                query: 'select event, count() from events group by event',
            },
        }

        const notebookContent = visualizationArtifactContentToNotebookArtifactContent(content)

        expect(notebookContent).toEqual({
            content_type: ArtifactContentType.Notebook,
            blocks: [
                {
                    type: 'visualization',
                    title: 'Create a pie chart',
                    query: content.query,
                },
            ],
        })
        expect(notebookArtifactContentToMarkdown(notebookContent)).toEqual(
            '<Query hideFilters query={{"kind":"DataVisualizationNode","source":{"kind":"HogQLQuery","query":"select event, count() from events group by event"},"display":"ActionsPie"}} title="Create a pie chart" />'
        )
    })

    it('detects inline comment marks anywhere in v1 content', () => {
        const withComment: JSONContent = {
            type: 'doc',
            content: [
                { type: 'paragraph', content: [{ type: 'text', text: 'plain' }] },
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'annotated', marks: [{ type: 'comment', attrs: { id: 'c1' } }] }],
                },
            ],
        }
        const withoutComment: JSONContent = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'bold', marks: [{ type: 'bold' }] }] }],
        }

        expect(notebookContentHasCommentMarks(withComment)).toBe(true)
        expect(notebookContentHasCommentMarks(withoutComment)).toBe(false)
        expect(notebookContentHasCommentMarks(null)).toBe(false)
    })

    it('converts v1 comment marks to ref highlights with comment threads', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'Numbers ' },
                        { type: 'text', text: 'look off', marks: [{ type: 'comment', attrs: { id: 'mark-1' } }] },
                        { type: 'text', text: ' here' },
                    ],
                },
                { type: 'paragraph', content: [{ type: 'text', text: 'Unrelated' }] },
            ],
        }

        const markdown = convertNotebookContentToMarkdown(content, {
            commentRepliesByMarkId: {
                'mark-1': [{ id: 'c1', author: 'Ann', text: 'Why is this lower?', at: '2026-01-01T00:00:00Z' }],
            },
        })

        expect(markdown).toEqual(
            [
                '<Comment ref="mark-1" replies={[{"id":"c1","author":"Ann","text":"Why is this lower?","at":"2026-01-01T00:00:00Z"}]} />',
                '',
                'Numbers <ref id="mark-1">look off</ref> here',
                '',
                'Unrelated',
            ].join('\n')
        )
        expect(parseMarkdownNotebook(markdown).errors).toEqual([])
    })

    it('emits an empty comment thread when no replies are provided for a mark', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'annotated', marks: [{ type: 'comment', attrs: { id: 'm1' } }] }],
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toEqual(
            '<Comment ref="m1" replies={[]} />\n\n<ref id="m1">annotated</ref>'
        )
    })

    it('wraps the ref outside other formatting marks', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'bolded',
                            marks: [{ type: 'bold' }, { type: 'comment', attrs: { id: 'm1' } }],
                        },
                    ],
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content)).toContain('<ref id="m1">**bolded**</ref>')
    })

    it('converts mentions to mention tags preserving the member id', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'Ping ' },
                        { type: NotebookNodeType.Mention, attrs: { id: 5 } },
                    ],
                },
            ],
        }

        expect(convertNotebookContentToMarkdown(content, { getMentionLabel: () => '@Marius' })).toEqual(
            'Ping <mention id="5">@Marius</mention>'
        )
        expect(convertNotebookContentToMarkdown(content)).toEqual('Ping <mention id="5">@member</mention>')
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

    describe('convertDroppedPostHogUrlToMarkdownNode', () => {
        // Entity links drag with only their href; this mapping is what turns a dropped link
        // into the resource's component node instead of a plain link.
        it.each<[string, string, { tagName: string; props: Record<string, unknown> } | null]>([
            ['feature flag', '/feature_flags/123', { tagName: 'FeatureFlag', props: { id: 123 } }],
            [
                'feature flag with project prefix',
                '/project/1/feature_flags/123',
                { tagName: 'FeatureFlag', props: { id: 123 } },
            ],
            ['experiment', '/experiments/42', { tagName: 'Experiment', props: { id: 42 } }],
            ['cohort', '/cohorts/7', { tagName: 'Cohort', props: { id: 7 } }],
            [
                'saved insight',
                '/insights/AbC123',
                {
                    tagName: 'Query',
                    props: { query: { kind: 'SavedInsightNode', shortId: 'AbC123' }, hideFilters: true },
                },
            ],
            [
                'survey',
                '/surveys/018f6a2b-0000-0000-0000-000000000000',
                { tagName: 'Survey', props: { id: '018f6a2b-0000-0000-0000-000000000000' } },
            ],
            [
                'recording',
                '/replay/018f6a2b-1111-2222-3333-444444444444',
                { tagName: 'Recording', props: { id: '018f6a2b-1111-2222-3333-444444444444' } },
            ],
            [
                'person by uuid',
                '/persons/018f6a2b-1111-2222-3333-444444444444',
                { tagName: 'Person', props: { id: '018f6a2b-1111-2222-3333-444444444444' } },
            ],
            [
                'person by distinct id',
                '/person/user%40example.com',
                { tagName: 'Person', props: { distinctId: 'user@example.com' } },
            ],
            ['new flag form (no entity yet)', '/feature_flags/new', null],
            ['new insight form (no entity yet)', '/insights/new', null],
            ['unrecognized path', '/settings/project', null],
        ])('%s', (_name, path, expected) => {
            const node = convertDroppedPostHogUrlToMarkdownNode(`${window.location.origin}${path}`)

            if (expected === null) {
                expect(node).toBeNull()
            } else {
                expect(node).toMatchObject({ type: 'component', ...expected })
            }
        })

        it('ignores URLs from other origins', () => {
            expect(convertDroppedPostHogUrlToMarkdownNode('https://example.com/feature_flags/123')).toBeNull()
        })
    })

    describe('convertDroppedRichContentNodeToMarkdownNode', () => {
        it('maps a dragged recording payload to its markdown component', () => {
            const node = convertDroppedRichContentNodeToMarkdownNode(NotebookNodeType.Recording, {
                id: 'session-1',
                noInspector: false,
            })

            expect(node).toMatchObject({
                type: 'component',
                tagName: 'Recording',
                props: { id: 'session-1', noInspector: false },
            })
        })

        it('defaults dropped queries to hidden filters', () => {
            const node = convertDroppedRichContentNodeToMarkdownNode(NotebookNodeType.Query, {
                query: { kind: NodeKind.EventsQuery, select: ['event'] },
            })

            expect(node).toMatchObject({ tagName: 'Query', props: { hideFilters: true } })
        })

        it('returns null for node types without a markdown counterpart', () => {
            expect(convertDroppedRichContentNodeToMarkdownNode('ph-not-a-real-node', { id: 1 })).toBeNull()
        })
    })
})
