import {
    escapeCodeSpanText,
    escapeInlineMarkdownText,
    escapeMarkdownBlockLines,
    makeEmptyParagraph,
    parseMarkdownNotebook,
    sanitizeNotebookLinkHref,
    serializeMarkdownNotebook,
    serializeNode,
} from 'lib/components/MarkdownNotebook/markdown'
import {
    NotebookBlockNode,
    NotebookComponentBlockNode,
    NotebookComponentProps,
    NotebookPropValue,
} from 'lib/components/MarkdownNotebook/types'
import { getInlineText, isNotebookPropValue, toSerializablePropValue } from 'lib/components/MarkdownNotebook/utils'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urlToResource } from 'scenes/urls'

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

export type NotebookContentForMarkdownConversion = JSONContent | JSONContent[] | string | null | undefined

const MARKDOWN_NOTEBOOK_NODE_ID = 'markdown-notebook-v2'

export const NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG: Partial<Record<NotebookNodeType, string>> = {
    [NotebookNodeType.Query]: 'Query',
    [NotebookNodeType.Python]: 'Python',
    [NotebookNodeType.PythonV2]: 'PythonV2',
    [NotebookNodeType.DuckSQL]: 'DuckSQL',
    [NotebookNodeType.HogQLSQL]: 'HogQLSQL',
    [NotebookNodeType.SQLV2]: 'SQLV2',
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

const RICH_CONTENT_NODE_TYPE_ALIASES: Record<string, string> = {
    bullet_list: 'bulletList',
    ordered_list: 'orderedList',
    list_item: 'listItem',
    code_block: 'codeBlock',
    table_row: 'tableRow',
    table_cell: 'tableCell',
    table_header: 'tableHeader',
}

export function isMarkdownNotebookContent(content: NotebookContentForMarkdownConversion): boolean {
    return !!getMarkdownNotebookNode(content)
}

export function getMarkdownNotebookMarkdown(content: NotebookContentForMarkdownConversion): string {
    return getMarkdownNotebookNode(content)?.attrs?.markdown ?? ''
}

export function getMarkdownNotebookNodeId(content: NotebookContentForMarkdownConversion): string {
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

/** Converts a dragged legacy notebook resource (`node` + `properties` dataTransfer payload, as set
 * by `useNotebookDrag`) into a markdown component block, or null when the node type has no
 * markdown counterpart. */
export function convertDroppedRichContentNodeToMarkdownNode(
    nodeType: string,
    attrs: Record<string, unknown>
): NotebookBlockNode | null {
    const tagName = NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG[nodeType as NotebookNodeType]
    if (!tagName) {
        return null
    }

    const props = getSerializableAttrs(attrs)
    return makeDroppedComponentNode(tagName, tagName === 'Query' ? withDefaultHiddenFilters(props) : props)
}

function makeDroppedComponentNode(tagName: string, props: NotebookComponentProps): NotebookComponentBlockNode {
    return {
        id: makeEmptyParagraph('dropped').id,
        type: 'component',
        tagName,
        props,
    }
}

function toNumericResourceId(ref: string): number | null {
    const id = Number(ref)
    return Number.isInteger(id) && id > 0 ? id : null
}

const REPLAY_SINGLE_PATH_REGEX = /^\/replay\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/
const PERSON_BY_UUID_PATH_REGEX = /^\/persons\/([^/]+)$/
const PERSON_BY_DISTINCT_ID_PATH_REGEX = /^\/person\/([^/]+)$/

/** Maps a dropped PostHog resource URL to its markdown component block, or null when the URL isn't
 * a recognized resource. Entity links (`Link`) drag with only their href, so this is what turns a
 * dragged feature flag, experiment, insight, etc. into its special node rather than a plain link. */
export function convertDroppedPostHogUrlToMarkdownNode(url: string): NotebookBlockNode | null {
    let parsed: URL
    try {
        parsed = new URL(url, window.location.origin)
    } catch {
        return null
    }
    if (parsed.origin !== window.location.origin) {
        return null
    }

    const path = removeProjectIdIfPresent(parsed.pathname)

    const replayMatch = path.match(REPLAY_SINGLE_PATH_REGEX)
    if (replayMatch) {
        return makeDroppedComponentNode('Recording', { id: replayMatch[1] })
    }
    const personByUuidMatch = path.match(PERSON_BY_UUID_PATH_REGEX)
    if (personByUuidMatch) {
        return makeDroppedComponentNode('Person', { id: decodeURIComponent(personByUuidMatch[1]) })
    }
    const personByDistinctIdMatch = path.match(PERSON_BY_DISTINCT_ID_PATH_REGEX)
    if (personByDistinctIdMatch) {
        return makeDroppedComponentNode('Person', { distinctId: decodeURIComponent(personByDistinctIdMatch[1]) })
    }

    const resource = urlToResource(path)
    if (!resource) {
        return null
    }

    switch (resource.type) {
        case 'feature_flag': {
            const id = toNumericResourceId(resource.ref)
            return id === null ? null : makeDroppedComponentNode('FeatureFlag', { id })
        }
        case 'experiment': {
            const id = toNumericResourceId(resource.ref)
            return id === null ? null : makeDroppedComponentNode('Experiment', { id })
        }
        case 'cohort': {
            const id = toNumericResourceId(resource.ref)
            return id === null ? null : makeDroppedComponentNode('Cohort', { id })
        }
        case 'insight':
            // `/insights/new` matches the same `:id` slot as a real short id
            return resource.ref === 'new'
                ? null
                : makeDroppedComponentNode('Query', {
                      query: { kind: NodeKind.SavedInsightNode, shortId: resource.ref },
                      hideFilters: true,
                  })
        case 'survey':
            return makeDroppedComponentNode('Survey', { id: resource.ref })
        case 'early_access_feature':
            return makeDroppedComponentNode('EarlyAccessFeature', { id: resource.ref })
        default:
            return null
    }
}

/** A paragraph holding the dropped URL as a link — the fallback when a dragged URL isn't a
 * recognized PostHog resource. */
export function buildDroppedLinkParagraphNode(url: string): NotebookBlockNode {
    const href = sanitizeNotebookLinkHref(url)
    return {
        id: makeEmptyParagraph('dropped-link').id,
        type: 'paragraph',
        children: [{ type: 'text', text: url, ...(href ? { marks: [{ type: 'link', href }] } : {}) }],
    }
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
 * Whether any node in a rich (v1) notebook carries an inline comment mark. The conversion
 * preserves them as `<ref>` highlights paired with `<Comment ref>` threads — callers can
 * use this to know whether to fetch the comment threads up front.
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

export type NotebookMarkdownConversionOptions = {
    /**
     * Replies per v1 comment mark id, embedded into the matching `<Comment ref>` tag so
     * the discussion travels with the markdown. Threads without an entry still get an
     * empty comment thread — the anchor must never be silently dropped.
     */
    commentRepliesByMarkId?: Record<string, NotebookPropValue[]>
    /** Display label for a mention (e.g. `@Marius`); falls back to `@member`. */
    getMentionLabel?: (memberId: number) => string | null
}

export function convertNotebookContentToMarkdown(
    content: NotebookContentForMarkdownConversion,
    options: NotebookMarkdownConversionOptions = {}
): string {
    const normalizedContent = normalizeNotebookContentForMarkdownConversion(content)

    if (typeof normalizedContent === 'string') {
        return normalizedContent
    }

    if (isMarkdownNotebookContent(normalizedContent)) {
        return getMarkdownNotebookMarkdown(normalizedContent)
    }

    const blocks: string[] = []
    const emittedCommentMarkIds = new Set<string>()
    for (const node of normalizedContent?.content ?? []) {
        // Each comment-marked range gets its thread right above the block holding the
        // highlight, so the margin-anchored thread aligns with the text it is about.
        for (const markId of collectCommentMarkIds(node)) {
            if (emittedCommentMarkIds.has(markId)) {
                continue
            }
            emittedCommentMarkIds.add(markId)
            blocks.push(
                serializeNode({
                    id: '',
                    type: 'component',
                    tagName: 'Comment',
                    props: { ref: markId, replies: options.commentRepliesByMarkId?.[markId] ?? [] },
                })
            )
        }

        const markdown = serializeRichContentNode(node, 0, options)
        if (markdown.trim().length > 0) {
            blocks.push(markdown)
        }
    }

    return blocks.join('\n\n')
}

function normalizeNotebookContentForMarkdownConversion(
    content: NotebookContentForMarkdownConversion
): JSONContent | string | null | undefined {
    if (typeof content === 'string') {
        const parsedContent = parseJsonEncodedNotebookContent(content)
        return parsedContent ?? content
    }

    if (Array.isArray(content)) {
        return { type: 'doc', content }
    }

    return content
}

function parseJsonEncodedNotebookContent(content: string): JSONContent | string | null {
    const trimmedContent = content.trim()
    if (
        !trimmedContent ||
        (!trimmedContent.startsWith('{') && !trimmedContent.startsWith('[') && !trimmedContent.startsWith('"'))
    ) {
        return null
    }

    try {
        const parsedContent = JSON.parse(trimmedContent) as unknown
        if (typeof parsedContent === 'string') {
            return parseJsonEncodedNotebookContent(parsedContent) ?? parsedContent
        }
        if (Array.isArray(parsedContent)) {
            return { type: 'doc', content: parsedContent as JSONContent[] }
        }
        if (parsedContent && typeof parsedContent === 'object') {
            return parsedContent as JSONContent
        }
    } catch {
        return null
    }

    return null
}

function collectCommentMarkIds(node: JSONContent): string[] {
    const markIds: string[] = []
    const visit = (current: JSONContent): void => {
        for (const mark of current.marks ?? []) {
            if (mark.type === 'comment' && typeof mark.attrs?.id === 'string' && mark.attrs.id) {
                markIds.push(mark.attrs.id)
            }
        }
        for (const child of current.content ?? []) {
            visit(child)
        }
    }
    visit(node)
    return markIds
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

function getMarkdownNotebookNode(content: NotebookContentForMarkdownConversion): MarkdownNotebookV2Node | null {
    if (!content || typeof content !== 'object' || Array.isArray(content)) {
        return null
    }
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
                    hideFilters: true,
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

function serializeRichContentNode(
    node: JSONContent,
    listDepth = 0,
    options: NotebookMarkdownConversionOptions = {}
): string {
    const nodeType = getRichContentNodeType(node)

    if (nodeType === 'text') {
        return escapeMarkdownBlockLines(serializeInlineNode(node, options))
    }

    if (nodeType === 'heading') {
        const level = typeof node.attrs?.level === 'number' ? Math.min(Math.max(node.attrs.level, 1), 6) : 1
        return `${'#'.repeat(level)} ${serializeInlineContent(node.content, options)}`
    }

    if (nodeType === 'paragraph') {
        return escapeMarkdownBlockLines(serializeInlineContent(node.content, options))
    }

    if (nodeType === 'blockquote') {
        return serializeBlockquoteNode(node, listDepth, options)
    }

    if (nodeType === 'bulletList' || nodeType === 'orderedList' || nodeType === 'taskList') {
        return serializeList(node, nodeType === 'orderedList', listDepth, options)
    }

    if (nodeType === 'horizontalRule') {
        return '---'
    }

    if (nodeType === 'codeBlock') {
        const language = typeof node.attrs?.language === 'string' ? node.attrs.language : ''
        // Code text must stay verbatim (no inline escaping), and serializeNode picks a fence
        // longer than any backtick run in the content
        const text = (node.content ?? [])
            .map((child) => (getRichContentNodeType(child) === 'hardBreak' ? '\n' : (child.text ?? '')))
            .join('')
        return serializeNode({ id: '', type: 'code', language: language || undefined, text })
    }

    if (nodeType === 'table') {
        return serializeTable(node, options)
    }

    if (nodeType === 'ph-text') {
        return serializeLegacyTextNode(node)
    }

    if (nodeType === 'ph-insight') {
        return serializeLegacyInsightNode(node)
    }

    if (nodeType === 'ph-dashboard') {
        return serializeLegacyDashboardNode(node)
    }

    if (nodeType === 'query') {
        return serializeLegacyQueryNode(node)
    }

    if (nodeType === 'ph-link') {
        return serializeLegacyLinkNode(node, options)
    }

    if (nodeType === 'callout') {
        return serializeCalloutNode(node, options)
    }

    const markdownTagName = nodeType ? NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG[nodeType as NotebookNodeType] : undefined
    if (markdownTagName) {
        return serializeNode({
            id: '',
            type: 'component',
            tagName: markdownTagName,
            props: withDefaultHiddenFilters(getSerializableAttrs(node.attrs)),
        })
    }

    const childMarkdown = (node.content ?? [])
        .map((child) => serializeRichContentNode(child, listDepth, options))
        .filter(Boolean)
        .join('\n\n')
    if (childMarkdown || !nodeType) {
        return childMarkdown
    }

    return serializeUnknownRichContentNode(node)
}

function serializeLegacyTextNode(node: JSONContent): string {
    const body = node.attrs?.body
    return typeof body === 'string' ? body : serializeUnknownRichContentNode(node)
}

function serializeLegacyInsightNode(node: JSONContent): string {
    const insightShortId = typeof node.attrs?.short_id === 'string' ? node.attrs.short_id : node.attrs?.id
    if (typeof insightShortId !== 'string' || !insightShortId) {
        return serializeUnknownRichContentNode(node)
    }

    return serializeNode({
        id: '',
        type: 'component',
        tagName: 'Query',
        props: withDefaultHiddenFilters({
            query: { kind: NodeKind.SavedInsightNode, shortId: insightShortId },
        }),
    })
}

function serializeLegacyDashboardNode(node: JSONContent): string {
    const dashboardId = node.attrs?.id
    if (typeof dashboardId !== 'string' && typeof dashboardId !== 'number') {
        return serializeUnknownRichContentNode(node)
    }

    return escapeMarkdownBlockLines(escapeInlineMarkdownText(`Dashboard ${String(dashboardId)}`))
}

function serializeLegacyQueryNode(node: JSONContent): string {
    const props = getSerializableAttrs(node.attrs)
    const query = props.query
    if (isNotebookObjectProp(query) && query.kind === NodeKind.HogQLQuery) {
        props.query = { kind: NodeKind.DataVisualizationNode, source: query }
    }

    return serializeNode({
        id: '',
        type: 'component',
        tagName: 'Query',
        props: withDefaultHiddenFilters(props),
    })
}

function serializeLegacyLinkNode(node: JSONContent, options: NotebookMarkdownConversionOptions = {}): string {
    const href = typeof node.attrs?.href === 'string' ? node.attrs.href : null
    const sanitizedHref = href ? sanitizeNotebookLinkHref(href) : null
    const label = serializeInlineContent(node.content, options).trim()

    if (sanitizedHref) {
        return `[${label || escapeInlineMarkdownText(sanitizedHref)}](${sanitizedHref})`
    }

    if (label) {
        return label
    }

    if (href?.trim()) {
        return escapeMarkdownBlockLines(escapeInlineMarkdownText(href.trim()))
    }

    return serializeUnknownRichContentNode(node)
}

// The markdown notebook blockquote only holds inline text (and list lines), so block content
// inside a v1 blockquote or callout — embedded cards like Query/Python, headings, code blocks,
// tables, nested quotes — is emitted as standalone blocks that split the quote. Quoting those
// lines instead would produce markdown the parser can only read back as escaped literal text,
// destroying the nodes on the next save.
function isBlockquotableRichContentNode(node: JSONContent, serialized: string): boolean {
    const nodeType = getRichContentNodeType(node)
    if (nodeType === 'paragraph' || nodeType === 'text') {
        return true
    }
    // Blockquoted headings parse back (`> ## Heading`), but only as a single line — a heading
    // whose content spilled onto extra lines splits out of the quote instead.
    if (nodeType === 'heading') {
        return !serialized.includes('\n')
    }
    // Blockquoted lists parse back (`> - item`), but only while every line is a list line — a
    // list that spilled block content into standalone blocks splits out of the quote with them.
    if (LIST_NODE_TYPES.has(nodeType ?? '')) {
        return !serialized.includes('\n\n')
    }
    return false
}

function serializeBlockquoteNode(
    node: JSONContent,
    listDepth: number,
    options: NotebookMarkdownConversionOptions = {}
): string {
    const blocks: string[] = []
    let pendingQuoteLines: string[] = []
    const flushQuoteLines = (): void => {
        if (pendingQuoteLines.length) {
            blocks.push(pendingQuoteLines.map((line) => `> ${line}`).join('\n'))
            pendingQuoteLines = []
        }
    }

    for (const child of node.content ?? []) {
        const childMarkdown = serializeRichContentNode(child, listDepth, options)
        if (isBlockquotableRichContentNode(child, childMarkdown)) {
            pendingQuoteLines.push(...childMarkdown.split('\n'))
        } else if (childMarkdown.trim()) {
            flushQuoteLines()
            blocks.push(childMarkdown)
        }
    }
    flushQuoteLines()

    return blocks.join('\n\n')
}

function serializeCalloutNode(node: JSONContent, options: NotebookMarkdownConversionOptions = {}): string {
    const emoji =
        typeof node.attrs?.emoji === 'string' && node.attrs.emoji.trim()
            ? escapeInlineMarkdownText(node.attrs.emoji.trim())
            : ''
    const blocks: string[] = []
    let pendingQuoteBodies: string[] = []
    let emojiPlaced = false
    const flushQuoteBodies = (): void => {
        if (!pendingQuoteBodies.length) {
            return
        }
        let body = pendingQuoteBodies.join('\n\n')
        if (emoji && !emojiPlaced) {
            body = `${emoji} ${body}`
            emojiPlaced = true
        }
        blocks.push(
            body
                .split('\n')
                .map((line) => `> ${line}`)
                .join('\n')
        )
        pendingQuoteBodies = []
    }

    for (const child of node.content ?? []) {
        const childMarkdown = serializeRichContentNode(child, 0, options)
        if (!childMarkdown.trim()) {
            continue
        }
        if (isBlockquotableRichContentNode(child, childMarkdown)) {
            pendingQuoteBodies.push(childMarkdown)
        } else {
            flushQuoteBodies()
            blocks.push(childMarkdown)
        }
    }
    flushQuoteBodies()

    if (emoji && !emojiPlaced) {
        blocks.unshift(`> ${emoji}`)
    }

    if (!blocks.length) {
        return serializeUnknownRichContentNode(node)
    }

    return blocks.join('\n\n')
}

function isNotebookObjectProp(value: NotebookPropValue | undefined): value is Record<string, NotebookPropValue> {
    return !!value && typeof value === 'object' && !Array.isArray(value)
}

function serializeUnknownRichContentNode(node: JSONContent): string {
    // An unmapped leaf node must not vanish on upgrade — preserve it as a component the
    // editor renders with its unknown-tag fallback
    const attrs = getSerializableAttrs(node.attrs)
    const props: NotebookComponentProps = node.type ? { nodeType: node.type, ...attrs } : attrs
    if (node.type) {
        props.nodeType = node.type
    }

    return serializeNode({
        id: '',
        type: 'component',
        tagName: 'UnknownNode',
        props,
    })
}

function serializeInlineContent(
    content: JSONContent[] | undefined,
    options: NotebookMarkdownConversionOptions = {}
): string {
    return (content ?? []).map((node) => serializeInlineNode(node, options)).join('')
}

function serializeInlineNode(node: JSONContent, options: NotebookMarkdownConversionOptions = {}): string {
    const nodeType = getRichContentNodeType(node)

    if (nodeType === 'text') {
        const isCodeText = (node.marks ?? []).some((mark) => mark.type === 'code')
        // Literal `*`/`` ` ``/`[` in legacy text must not become formatting after the upgrade
        const escapedText = isCodeText ? escapeCodeSpanText(node.text ?? '') : escapeInlineMarkdownText(node.text ?? '')
        return applyMarks(escapedText, node.marks)
    }
    if (nodeType === 'hardBreak') {
        return '\n'
    }
    if (nodeType === NotebookNodeType.Mention) {
        return serializeMentionNode(node, options)
    }
    return serializeInlineContent(node.content, options)
}

/** Mentions keep their member id: `<mention id="5">@Marius</mention>`. */
function serializeMentionNode(node: JSONContent, options: NotebookMarkdownConversionOptions): string {
    const memberId = typeof node.attrs?.id === 'number' ? node.attrs.id : null
    const attrLabel = typeof node.attrs?.label === 'string' && node.attrs.label.trim() ? node.attrs.label.trim() : null
    const lookedUpLabel = memberId !== null ? options.getMentionLabel?.(memberId) : null
    const label = attrLabel ?? lookedUpLabel ?? '@member'
    const displayLabel = label.startsWith('@') ? label : `@${label}`
    if (memberId === null) {
        return escapeInlineMarkdownText(displayLabel)
    }
    return `<mention id=${JSON.stringify(String(memberId))}>${escapeInlineMarkdownText(displayLabel)}</mention>`
}

function applyMarks(text: string, marks: JSONContent['marks']): string {
    // Comment marks become `<ref>` anchors and wrap outermost, so the tag encloses the
    // fully formatted text.
    const commentMarkIds = (marks ?? [])
        .filter((mark) => mark.type === 'comment' && typeof mark.attrs?.id === 'string' && mark.attrs.id)
        .map((mark) => mark.attrs?.id as string)
    const formattedText = applyFormattingMarks(text, marks)
    return commentMarkIds.reduce(
        (markedText, markId) => `<ref id=${JSON.stringify(markId)}>${markedText}</ref>`,
        formattedText
    )
}

function applyFormattingMarks(text: string, marks: JSONContent['marks']): string {
    return (marks ?? []).reduce((markedText, mark) => {
        if (mark.type === 'bold' || mark.type === 'strong') {
            return `**${markedText}**`
        }
        if (mark.type === 'italic' || mark.type === 'em') {
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

function getRichContentNodeType(node: JSONContent): string | undefined {
    return node.type ? (RICH_CONTENT_NODE_TYPE_ALIASES[node.type] ?? node.type) : undefined
}

function serializeList(
    node: JSONContent,
    ordered: boolean,
    depth: number,
    options: NotebookMarkdownConversionOptions = {}
): string {
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

    const items = (node.content ?? []).filter((child) => LIST_ITEM_NODE_TYPES.has(getRichContentNodeType(child) ?? ''))
    items.forEach((item, index) => {
        const { listLines, trailingBlocks } = serializeListItem(item, ordered, depth, index, options)
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
    index: number,
    options: NotebookMarkdownConversionOptions = {}
): { listLines: string[]; trailingBlocks: string[] } {
    const marker = ordered ? `${index + 1}.` : '-'
    const children = item.content ?? []
    const itemType = getRichContentNodeType(item)
    const firstParagraph = children.find((child) => getRichContentNodeType(child) === 'paragraph')
    const nestedLists = children.filter((child) => LIST_NODE_TYPES.has(getRichContentNodeType(child) ?? ''))
    const extraBlocks = children.filter(
        (child) => child !== firstParagraph && !LIST_NODE_TYPES.has(getRichContentNodeType(child) ?? '')
    )
    const checkbox = itemType === 'taskItem' ? (item.attrs?.checked ? '[x] ' : '[ ] ') : ''
    // List lines cannot contain raw newlines in the markdown notebook model
    const itemText = (firstParagraph ? serializeInlineContent(firstParagraph.content, options) : '').replace(
        /\s*\n\s*/g,
        ' '
    )
    const listLines = [`${'  '.repeat(depth)}${marker} ${checkbox}${itemText}`.trimEnd()]

    for (const nestedList of nestedLists) {
        const nestedMarkdown = serializeRichContentNode(nestedList, depth + 1, options)
        if (nestedMarkdown) {
            listLines.push(nestedMarkdown)
        }
    }

    const trailingBlocks = extraBlocks
        .map((child) => serializeRichContentNode(child, 0, options))
        .filter((block) => block.trim().length > 0)

    return { listLines, trailingBlocks }
}

function serializeTable(node: JSONContent, options: NotebookMarkdownConversionOptions = {}): string {
    const rows = (node.content ?? []).filter((child) => getRichContentNodeType(child) === 'tableRow')
    if (!rows.length) {
        return ''
    }

    const serializedRows = rows.map((row) =>
        (row.content ?? [])
            .filter(
                (cell) => getRichContentNodeType(cell) === 'tableCell' || getRichContentNodeType(cell) === 'tableHeader'
            )
            .map((cell) =>
                (cell.content ?? [])
                    .map((child) => serializeRichContentNode(child, 0, options))
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
        const serializableValue = toSerializablePropValue(reviveJsonEncodedAttr(value))
        if (serializableValue !== undefined) {
            props[key] = serializableValue
        }
        return props
    }, {})
}

function withDefaultHiddenFilters(props: NotebookComponentProps): NotebookComponentProps {
    if (typeof props.hideFilters === 'boolean' || typeof props.edit === 'boolean') {
        return props
    }
    return { ...props, hideFilters: true }
}

// Widget node attributes round-trip through HTML as JSON strings (NodeWrapper's jsonAttr), so a
// persisted v1 node can carry an attr like `query` as the JSON *string* `'{"kind":...}'` rather than
// the object. Serializing that string verbatim emits `query="..."`, which parses back as a string and
// renders an empty Query node. Revive object/array-shaped JSON strings to their real value so they
// serialize as `query={{...}}`. Only `{`/`[`-prefixed strings are touched, so plain text and HogQL
// query strings (which never start that way) are left untouched.
function reviveJsonEncodedAttr(value: unknown): unknown {
    if (typeof value !== 'string') {
        return value
    }
    const trimmed = value.trim()
    if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
        return value
    }
    try {
        const parsed = JSON.parse(trimmed) as unknown
        return parsed !== null && typeof parsed === 'object' ? parsed : value
    } catch {
        return value
    }
}
