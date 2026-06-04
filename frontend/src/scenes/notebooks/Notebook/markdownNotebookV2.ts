import { serializeNode } from 'lib/components/MarkdownNotebook/markdown'
import { NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'
import { isNotebookPropValue } from 'lib/components/MarkdownNotebook/utils'
import { JSONContent } from 'lib/components/RichContentEditor/types'

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
    const firstHeading = getMarkdownNotebookMarkdown(content).match(/^#\s+(.+)$/m)
    return firstHeading?.[1]?.trim() || null
}

function getMarkdownNotebookNode(content: JSONContent | null | undefined): MarkdownNotebookV2Node | null {
    const nodes = content?.content ?? []
    if (nodes.length !== 1 || nodes[0]?.type !== NotebookNodeType.MarkdownNotebook) {
        return null
    }
    return nodes[0] as MarkdownNotebookV2Node
}

function serializeRichContentNode(node: JSONContent, listDepth = 0): string {
    if (node.type === 'heading') {
        const level = typeof node.attrs?.level === 'number' ? Math.min(Math.max(node.attrs.level, 1), 6) : 1
        return `${'#'.repeat(level)} ${serializeInlineContent(node.content)}`
    }

    if (node.type === 'paragraph') {
        return serializeInlineContent(node.content)
    }

    if (node.type === 'blockquote') {
        return (node.content ?? [])
            .map((child) => serializeRichContentNode(child, listDepth))
            .join('\n')
            .split('\n')
            .map((line) => `> ${line}`)
            .join('\n')
    }

    if (node.type === 'bulletList' || node.type === 'orderedList') {
        return serializeList(node, node.type === 'orderedList', listDepth)
    }

    if (node.type === 'codeBlock') {
        const language = typeof node.attrs?.language === 'string' ? node.attrs.language : ''
        return `\`\`\`${language}\n${serializeInlineContent(node.content)}\n\`\`\``
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

    return (node.content ?? [])
        .map((child) => serializeRichContentNode(child, listDepth))
        .filter(Boolean)
        .join('\n\n')
}

function serializeInlineContent(content: JSONContent[] | undefined): string {
    return (content ?? []).map(serializeInlineNode).join('')
}

function serializeInlineNode(node: JSONContent): string {
    if (node.type === 'text') {
        return applyMarks(node.text ?? '', node.marks)
    }
    if (node.type === 'hardBreak') {
        return '\n'
    }
    if (node.type === NotebookNodeType.Mention) {
        return typeof node.attrs?.label === 'string' ? node.attrs.label : ''
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
        if (mark.type === 'code') {
            return `\`${markedText}\``
        }
        if (mark.type === 'link' && typeof mark.attrs?.href === 'string') {
            return `[${markedText}](${mark.attrs.href})`
        }
        return markedText
    }, text)
}

function serializeList(node: JSONContent, ordered: boolean, depth: number): string {
    return (node.content ?? [])
        .filter((child) => child.type === 'listItem')
        .map((item, index) => serializeListItem(item, ordered, depth, index))
        .join('\n')
}

function serializeListItem(item: JSONContent, ordered: boolean, depth: number, index: number): string {
    const marker = ordered ? `${index + 1}.` : '-'
    const children = item.content ?? []
    const firstParagraph = children.find((child) => child.type === 'paragraph')
    const nestedLists = children.filter((child) => child.type === 'bulletList' || child.type === 'orderedList')
    const itemText = firstParagraph ? serializeInlineContent(firstParagraph.content) : ''
    const nestedMarkdown = nestedLists
        .map((child) => serializeRichContentNode(child, depth + 1))
        .filter(Boolean)
        .join('\n')
    const currentLine = `${'  '.repeat(depth)}${marker} ${itemText}`

    return nestedMarkdown ? `${currentLine}\n${nestedMarkdown}` : currentLine
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
                    .replace(/\|/g, '\\|')
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
