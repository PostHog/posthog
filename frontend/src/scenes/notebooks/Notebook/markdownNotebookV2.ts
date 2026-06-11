import {
    escapeCodeSpanText,
    escapeInlineMarkdownText,
    escapeMarkdownBlockLines,
    parseMarkdownNotebook,
    sanitizeNotebookLinkHref,
    serializeMarkdownNotebook,
    serializeNode,
} from 'lib/components/MarkdownNotebook/markdown'
import { NotebookBlockNode, NotebookComponentProps, NotebookPropValue } from 'lib/components/MarkdownNotebook/types'
import { getInlineText, isNotebookPropValue } from 'lib/components/MarkdownNotebook/utils'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { DocumentBlock, VisualizationBlock } from '~/queries/schema/schema-assistant-artifacts'
import {
    ArtifactContentType,
    NotebookArtifactContent,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode, NodeKind, QuerySchemaRoot } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isHogQLQuery, isInsightQueryNode } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { NotebookNodeType } from '../types'

export type MarkdownNotebookV2Node = {
    type: NotebookNodeType.MarkdownNotebook
    attrs?: {
        nodeId?: string
        markdown?: string
    }
}

const MARKDOWN_NOTEBOOK_NODE_ID = 'markdown-notebook-v2'

const NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG: Partial<Record<NotebookNodeType, string>> = {
    [NotebookNodeType.Query]: 'Query',
    [NotebookNodeType.Python]: 'Python',
    [NotebookNodeType.DuckSQL]: 'DuckSQL',
    [NotebookNodeType.HogQLSQL]: 'HogQLSQL',
    [NotebookNodeType.Recording]: 'Recording',
    [NotebookNodeType.RecordingPlaylist]: 'RecordingPlaylist',
    [NotebookNodeType.FeatureFlag]: 'FeatureFlag',
    [NotebookNodeType.FeatureFlagCodeExample]: 'FeatureFlagCodeExample',
    [NotebookNodeType.Experiment]: 'Experiment',
    [NotebookNodeType.EarlyAccessFeature]: 'EarlyAccessFeature',
    [NotebookNodeType.Survey]: 'Survey',
    [NotebookNodeType.Person]: 'Person',
    [NotebookNodeType.Group]: 'Group',
    [NotebookNodeType.Cohort]: 'Cohort',
    [NotebookNodeType.Backlink]: 'Backlink',
    [NotebookNodeType.ReplayTimestamp]: 'ReplayTimestamp',
    [NotebookNodeType.Image]: 'Image',
    [NotebookNodeType.PersonFeed]: 'PersonFeed',
    [NotebookNodeType.PersonProperties]: 'PersonProperties',
    [NotebookNodeType.GroupProperties]: 'GroupProperties',
    [NotebookNodeType.Map]: 'Map',
    [NotebookNodeType.Embed]: 'Embed',
    [NotebookNodeType.Latex]: 'Latex',
    [NotebookNodeType.TaskCreate]: 'TaskCreate',
    [NotebookNodeType.LLMTrace]: 'LLMTrace',
    [NotebookNodeType.Issues]: 'Issues',
    [NotebookNodeType.UsageMetrics]: 'UsageMetrics',
    [NotebookNodeType.ZendeskTickets]: 'ZendeskTickets',
    [NotebookNodeType.RelatedGroups]: 'RelatedGroups',
    [NotebookNodeType.CustomerJourney]: 'CustomerJourney',
    [NotebookNodeType.SupportTickets]: 'SupportTickets',
}

export function isMarkdownNotebookContent(content: JSONContent | null | undefined): boolean {
    return !!getMarkdownNotebookNode(content)
}

export function getMarkdownNotebookMarkdown(content: JSONContent | null | undefined): string {
    return getMarkdownNotebookNode(content)?.attrs?.markdown ?? ''
}

export function getMarkdownNotebookNodeId(content: JSONContent | null | undefined): string {
    return getMarkdownNotebookNode(content)?.attrs?.nodeId ?? MARKDOWN_NOTEBOOK_NODE_ID
}

export function buildMarkdownNotebookContent(markdown: string, nodeId = MARKDOWN_NOTEBOOK_NODE_ID): JSONContent {
    return {
        type: 'doc',
        content: [
            {
                type: NotebookNodeType.MarkdownNotebook,
                attrs: {
                    nodeId,
                    markdown,
                },
            },
        ],
    }
}

export function appendMarkdownNotebookBlock(
    content: JSONContent | null | undefined,
    blockMarkdown: string
): JSONContent {
    const markdown = getMarkdownNotebookMarkdown(content)
    return buildMarkdownNotebookContent(
        [markdown, blockMarkdown].filter((block) => block.trim()).join('\n\n'),
        getMarkdownNotebookNodeId(content)
    )
}

export function serializeMarkdownNotebookComponent(tagName: string, props: NotebookComponentProps): string {
    return serializeNode({
        id: '',
        type: 'component',
        tagName,
        props,
    })
}

export function notebookArtifactContentToMarkdown(content: NotebookArtifactContent): string {
    const nodes = content.blocks.flatMap(notebookArtifactBlockToMarkdownNodes)
    const markdown = serializeMarkdownNotebook({ type: 'doc', nodes, errors: [] })
    const title = normalizeArtifactTitle(content.title)
    const hasTitleHeading = nodes.some((node) => node.type === 'heading' && (node.level ?? 1) === 1)

    if (!title || hasTitleHeading) {
        return markdown
    }

    return [`# ${title}`, markdown].filter((block) => block.trim()).join('\n\n')
}

export function visualizationArtifactContentToNotebookArtifactContent(
    content: VisualizationArtifactContent
): NotebookArtifactContent {
    return {
        content_type: ArtifactContentType.Notebook,
        blocks: [
            {
                type: 'visualization',
                query: content.query as VisualizationBlock['query'],
                title: getVisualizationArtifactTitle(content),
            },
        ],
    }
}

/**
 * Whether any node in a rich (v1) notebook carries an inline comment mark. Markdown has no
 * slot for range-anchored comment marks, so the conversion drops them — callers must warn.
 */
export function notebookContentHasCommentMarks(content: JSONContent | null | undefined): boolean {
    if (!content) {
        return false
    }
    if ((content.marks ?? []).some((mark) => mark.type === 'comment')) {
        return true
    }
    return (content.content ?? []).some((child) => notebookContentHasCommentMarks(child))
}

export function convertNotebookContentToMarkdown(content: JSONContent | null | undefined): string {
    if (isMarkdownNotebookContent(content)) {
        return getMarkdownNotebookMarkdown(content)
    }

    return (content?.content ?? [])
        .map((node) => serializeRichContentNode(node))
        .filter((markdown) => markdown.trim().length > 0)
        .join('\n\n')
}

export function getMarkdownNotebookTextContent(content: JSONContent | null | undefined): string | null {
    if (!isMarkdownNotebookContent(content)) {
        return null
    }
    return getMarkdownNotebookMarkdown(content)
}

export function getMarkdownNotebookTitle(content: JSONContent | null | undefined): string | null {
    const markdown = getMarkdownNotebookMarkdown(content)
    if (!markdown) {
        return null
    }

    // Parse instead of regexing the raw markdown, so `# comment` lines inside code blocks
    // can't be mistaken for the title
    const firstHeading = parseMarkdownNotebook(markdown).nodes.find(
        (node) => node.type === 'heading' && (node.level ?? 1) === 1
    )
    if (firstHeading?.type !== 'heading') {
        return null
    }

    return getInlineText(firstHeading.children).trim() || null
}

function getMarkdownNotebookNode(content: JSONContent | null | undefined): MarkdownNotebookV2Node | null {
    const nodes = content?.content ?? []
    if (nodes.length !== 1 || nodes[0]?.type !== NotebookNodeType.MarkdownNotebook) {
        return null
    }
    return nodes[0] as MarkdownNotebookV2Node
}

function notebookArtifactBlockToMarkdownNodes(block: DocumentBlock): NotebookBlockNode[] {
    if (block.type === 'markdown') {
        return parseMarkdownNotebook(block.content).nodes
    }

    if (block.type === 'visualization') {
        const query = getNotebookArtifactVisualizationQuery(block)
        if (!query) {
            return []
        }

        return [
            {
                id: '',
                type: 'component',
                tagName: 'Query',
                props: {
                    query,
                    ...getOptionalTitleProp(block.title),
                },
            },
        ]
    }

    if (block.type === 'session_replay') {
        return [
            {
                id: '',
                type: 'component',
                tagName: 'Recording',
                props: {
                    id: block.session_id,
                    timestampMs: block.timestamp_ms,
                    ...getOptionalTitleProp(block.title),
                },
            },
        ]
    }

    return []
}

function getNotebookArtifactVisualizationQuery(block: VisualizationBlock): NotebookPropValue | null {
    const source = block.query as QuerySchemaRoot
    const display = getNotebookArtifactVisualizationDisplay(block)
    const query: QuerySchemaRoot | DataVisualizationNode | InsightVizNode = isHogQLQuery(source)
        ? { kind: NodeKind.DataVisualizationNode, source, ...(display ? { display } : {}) }
        : isDataVisualizationNode(source) && !source.display && display
          ? { ...source, display }
          : isInsightQueryNode(source)
            ? { kind: NodeKind.InsightVizNode, source, showHeader: true }
            : source

    return toNotebookPropValue(query)
}

function getNotebookArtifactVisualizationDisplay(block: VisualizationBlock): ChartDisplayType | null {
    return /\bpie\b/i.test(block.title ?? '') ? ChartDisplayType.ActionsPie : null
}

function getVisualizationArtifactTitle(content: VisualizationArtifactContent): string | null {
    return (
        normalizeArtifactTitle(content.name) ??
        normalizeArtifactTitle(content.plan) ??
        normalizeArtifactTitle(content.description)
    )
}

function getOptionalTitleProp(title: string | null | undefined): Partial<Pick<NotebookComponentProps, 'title'>> {
    return title?.trim() ? { title: title.trim() } : {}
}

function normalizeArtifactTitle(title: string | null | undefined): string | null {
    const normalizedTitle = title?.replace(/\s+/g, ' ').trim()
    return normalizedTitle || null
}

function toNotebookPropValue(value: unknown): NotebookPropValue | null {
    const serializedValue = JSON.stringify(value)
    if (serializedValue === undefined) {
        return null
    }

    const parsedValue = JSON.parse(serializedValue) as unknown
    return isNotebookPropValue(parsedValue) ? parsedValue : null
}

function serializeRichContentNode(node: JSONContent, listDepth = 0): string {
    if (node.type === 'heading') {
        const level = typeof node.attrs?.level === 'number' ? Math.min(Math.max(node.attrs.level, 1), 6) : 1
        return `${'#'.repeat(level)} ${serializeInlineContent(node.content)}`
    }

    if (node.type === 'paragraph') {
        return escapeMarkdownBlockLines(serializeInlineContent(node.content))
    }

    if (node.type === 'blockquote') {
        return (node.content ?? [])
            .map((child) => serializeRichContentNode(child, listDepth))
            .join('\n')
            .split('\n')
            .map((line) => `> ${line}`)
            .join('\n')
    }

    if (node.type === 'bulletList' || node.type === 'orderedList' || node.type === 'taskList') {
        return serializeList(node, node.type === 'orderedList', listDepth)
    }

    if (node.type === 'horizontalRule') {
        return '---'
    }

    if (node.type === 'codeBlock') {
        const language = typeof node.attrs?.language === 'string' ? node.attrs.language : ''
        // Code text must stay verbatim (no inline escaping), and serializeNode picks a fence
        // longer than any backtick run in the content
        const text = (node.content ?? [])
            .map((child) => (child.type === 'hardBreak' ? '\n' : (child.text ?? '')))
            .join('')
        return serializeNode({ id: '', type: 'code', language: language || undefined, text })
    }

    if (node.type === 'table') {
        return serializeTable(node)
    }

    const markdownTagName = NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG[node.type as NotebookNodeType]
    if (markdownTagName) {
        return serializeNode({
            id: '',
            type: 'component',
            tagName: markdownTagName,
            props: getSerializableAttrs(node.attrs),
        })
    }

    const childMarkdown = (node.content ?? [])
        .map((child) => serializeRichContentNode(child, listDepth))
        .filter(Boolean)
        .join('\n\n')
    if (childMarkdown || !node.type) {
        return childMarkdown
    }

    // An unmapped leaf node must not vanish on upgrade — preserve it as a component the
    // editor renders with its unknown-tag fallback
    return serializeNode({
        id: '',
        type: 'component',
        tagName: 'UnknownNode',
        props: { nodeType: node.type, ...getSerializableAttrs(node.attrs) },
    })
}

function serializeInlineContent(content: JSONContent[] | undefined): string {
    return (content ?? []).map(serializeInlineNode).join('')
}

function serializeInlineNode(node: JSONContent): string {
    if (node.type === 'text') {
        const isCodeText = (node.marks ?? []).some((mark) => mark.type === 'code')
        // Literal `*`/`` ` ``/`[` in legacy text must not become formatting after the upgrade
        const escapedText = isCodeText ? escapeCodeSpanText(node.text ?? '') : escapeInlineMarkdownText(node.text ?? '')
        return applyMarks(escapedText, node.marks)
    }
    if (node.type === 'hardBreak') {
        return '\n'
    }
    if (node.type === NotebookNodeType.Mention) {
        return typeof node.attrs?.label === 'string' ? escapeInlineMarkdownText(node.attrs.label) : ''
    }
    return serializeInlineContent(node.content)
}

function applyMarks(text: string, marks: JSONContent['marks']): string {
    return (marks ?? []).reduce((markedText, mark) => {
        if (mark.type === 'bold') {
            return `**${markedText}**`
        }
        if (mark.type === 'italic') {
            return `*${markedText}*`
        }
        if (mark.type === 'underline') {
            return `<u>${markedText}</u>`
        }
        if (mark.type === 'strike') {
            return `~~${markedText}~~`
        }
        if (mark.type === 'code') {
            return `\`${markedText}\``
        }
        if (mark.type === 'link' && typeof mark.attrs?.href === 'string') {
            const href = sanitizeNotebookLinkHref(mark.attrs.href)
            return href ? `[${markedText}](${href})` : markedText
        }
        return markedText
    }, text)
}

const LIST_NODE_TYPES = new Set(['bulletList', 'orderedList', 'taskList'])
const LIST_ITEM_NODE_TYPES = new Set(['listItem', 'taskItem'])

function serializeList(node: JSONContent, ordered: boolean, depth: number): string {
    // The markdown notebook list model only holds one inline line per item, so block content inside a
    // list item (extra paragraphs, code blocks, quotes) is emitted as standalone blocks after the item,
    // splitting the list rather than dropping the content.
    const blocks: string[] = []
    let pendingListLines: string[] = []
    const flushListLines = (): void => {
        if (pendingListLines.length) {
            blocks.push(pendingListLines.join('\n'))
            pendingListLines = []
        }
    }

    const items = (node.content ?? []).filter((child) => LIST_ITEM_NODE_TYPES.has(child.type ?? ''))
    items.forEach((item, index) => {
        const { listLines, trailingBlocks } = serializeListItem(item, ordered, depth, index)
        pendingListLines.push(...listLines)
        if (trailingBlocks.length) {
            flushListLines()
            blocks.push(...trailingBlocks)
        }
    })
    flushListLines()

    return blocks.join('\n\n')
}

function serializeListItem(
    item: JSONContent,
    ordered: boolean,
    depth: number,
    index: number
): { listLines: string[]; trailingBlocks: string[] } {
    const marker = ordered ? `${index + 1}.` : '-'
    const children = item.content ?? []
    const firstParagraph = children.find((child) => child.type === 'paragraph')
    const nestedLists = children.filter((child) => LIST_NODE_TYPES.has(child.type ?? ''))
    const extraBlocks = children.filter((child) => child !== firstParagraph && !LIST_NODE_TYPES.has(child.type ?? ''))
    const checkbox = item.type === 'taskItem' ? (item.attrs?.checked ? '[x] ' : '[ ] ') : ''
    // List lines cannot contain raw newlines in the markdown notebook model
    const itemText = (firstParagraph ? serializeInlineContent(firstParagraph.content) : '').replace(/\s*\n\s*/g, ' ')
    const listLines = [`${'  '.repeat(depth)}${marker} ${checkbox}${itemText}`.trimEnd()]

    for (const nestedList of nestedLists) {
        const nestedMarkdown = serializeRichContentNode(nestedList, depth + 1)
        if (nestedMarkdown) {
            listLines.push(nestedMarkdown)
        }
    }

    const trailingBlocks = extraBlocks
        .map((child) => serializeRichContentNode(child))
        .filter((block) => block.trim().length > 0)

    return { listLines, trailingBlocks }
}

function serializeTable(node: JSONContent): string {
    const rows = (node.content ?? []).filter((child) => child.type === 'tableRow')
    if (!rows.length) {
        return ''
    }

    const serializedRows = rows.map((row) =>
        (row.content ?? [])
            .filter((cell) => cell.type === 'tableCell' || cell.type === 'tableHeader')
            .map((cell) =>
                (cell.content ?? [])
                    .map((child) => serializeRichContentNode(child))
                    .join(' ')
                    .replace(/\s*\n\s*/g, ' ')
                    // Plain-text pipes are already escaped inline; only escape the rest (code spans),
                    // skipping `\X` pairs so they aren't double-escaped
                    .replace(/\\[\s\S]|\|/g, (match) => (match === '|' ? '\\|' : match))
            )
    )
    const columnCount = Math.max(...serializedRows.map((row) => row.length))
    const header = normalizeTableRow(serializedRows[0], columnCount)
    const body = serializedRows.slice(1).map((row) => normalizeTableRow(row, columnCount))
    const separator = Array.from({ length: columnCount }, () => '---')
    const rowsToRender = [header, separator, ...body]

    return rowsToRender.map((row) => `| ${row.join(' | ')} |`).join('\n')
}

function normalizeTableRow(row: string[] | undefined, columnCount: number): string[] {
    return Array.from({ length: columnCount }, (_, index) => row?.[index] ?? '')
}

function getSerializableAttrs(attrs: Record<string, unknown> | undefined): NotebookComponentProps {
    return Object.entries(attrs ?? {}).reduce<NotebookComponentProps>((props, [key, value]) => {
        if (isNotebookPropValue(value)) {
            props[key] = value
        }
        return props
    }, {})
}
