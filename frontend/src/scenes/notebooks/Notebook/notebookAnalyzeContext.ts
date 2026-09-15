import type { NotebookBlockNode, NotebookPropValue } from 'lib/components/MarkdownNotebook/types'
import type { JSONContent } from 'lib/components/RichContentEditor/types'
import { uuid } from 'lib/utils/dom'
import { urls } from 'scenes/urls'

import { NodeKind, type QuerySchema } from '~/queries/schema/schema-general'
import type { InsightShortId } from '~/types'

import type { AttachedContextItem, ComposerFocus } from 'products/posthog_ai/frontend/api/types'
import type { VisualizationArtifactActionPayload } from 'products/posthog_ai/frontend/api/types'

import { NotebookNodeType } from '../types'
import { getSqlV2PropsFromQueryProp } from './markdownNotebookV2'

/** Which of the four analyzable cell shapes a cell is, and therefore what its body looks like. */
export type NotebookAnalyzeCellKind = 'insight' | 'query' | 'sql' | 'python'

export interface NotebookAnalyzeCell {
    notebookShortId: string
    nodeId: string
    nodeType: NotebookNodeType
    kind: NotebookAnalyzeCellKind
    title?: string
    insightShortId?: string
    query?: QuerySchema
    code?: string
    /** The name later cells use to reference this cell's result. */
    dataframeName?: string
    /** A direct-query data source id, or absent when the cell runs against PostHog's ClickHouse. */
    connectionId?: string
}

/** The cell attributes this module reads, narrowed from the node's own (loosely typed) attributes. */
export interface NotebookAnalyzeCellAttributes {
    nodeId?: string
    title?: string
    query?: unknown
    id?: string
    code?: string
    returnVariable?: string
    connectionId?: string | null
}

/** One provider id for the whole notebook, so analyzing a second cell replaces the first cell's context. */
export const NOTEBOOK_ANALYZE_PROVIDER_ID = 'notebook-analyze-cell'

/** Closing any chip of the set detaches the hidden instruction and the cell body with it. */
export const NOTEBOOK_ANALYZE_CONTEXT_GROUP = 'notebook-analyze-cell'

/**
 * Past this many characters the cell body is dropped from the context item and the agent reads it
 * with `notebooks-get` instead. A pasted-in query or a long Python cell would otherwise ride every
 * message of the conversation.
 */
const NOTEBOOK_ANALYZE_CELL_VALUE_BUDGET = 16_000

const CELL_KIND_LABELS: Record<NotebookAnalyzeCellKind, string> = {
    insight: 'Insight',
    query: 'Chart',
    sql: 'SQL cell',
    python: 'Python cell',
}

const CELL_KIND_PROMPTS: Record<NotebookAnalyzeCellKind, string> = {
    insight: 'Analyze this chart further',
    query: 'Analyze this chart further',
    sql: 'Analyze this SQL cell further',
    python: 'Analyze this Python cell further',
}

/** The composer headline when the cell has nothing to preview, so no focus card replaces the welcome state. */
const CELL_KIND_HEADLINES: Record<NotebookAnalyzeCellKind, string> = {
    insight: 'Ask about this insight',
    query: 'Ask about this chart',
    sql: 'Ask about this SQL cell',
    python: 'Ask about this Python cell',
}

export const NOTEBOOK_ANALYZE_FOCUS_CAPTION = 'PostHog AI can see this notebook and this cell.'

/**
 * The outline lists at most this many cells. Past it, the cells nearest the analyzed one are kept, half
 * before and half after, because those are the ones a question about this cell most likely needs.
 */
export const NOTEBOOK_OUTLINE_CELL_CAP = 60

const NOTEBOOK_ANALYZE_INSTRUCTIONS =
    'The user is looking at one cell of a PostHog notebook and is asking about it. The attached ' +
    'notebook_cell item is that cell: `node_id` identifies it inside the notebook, `cell_type` is one of ' +
    'insight, query, sql or python, and the body arrives as `insight_short_id`, `query` (an insight query ' +
    'schema) or `code` (HogQL for a sql cell, Python for a python cell). `dataframe_name` is the name later ' +
    'cells use to reference this cell. When `query_elided` is true the body was too large to attach, so ' +
    'read the cell with the notebooks-get tool. ' +
    'The cell is pinned above the chat, so the user already sees it: refer to it as "this chart" or "this ' +
    'cell" and do not describe its definition back to them. ' +
    'The notebook_outline item lists the notebook cells in document order, each with `node_id`, `cell_type`, ' +
    '`title` and `dataframe_name` but no body. `analyzed` marks the cell the user asked about, and ' +
    '`truncated` is true when cells far from it were left out. Use the outline to answer questions about ' +
    'how cells relate, and read cell bodies with notebooks-get or notebooks-list-frames only when the ' +
    'question needs them. ' +
    'Answer with data rather than from the query definition alone: run execute-sql, insight-query or the ' +
    'query-trends, query-funnel, query-retention and other query tools. ' +
    'Do not change the notebook unless the user asks you to. Every chart and query result you produce ' +
    'carries an "Add to notebook" button, so the user chooses which results become cells.'

/**
 * Reads the cell a notebook node stands for, or null when the node type is not one a reader can
 * analyze. `attributes.id` is what separates a saved insight from an inline query: the node renders
 * the saved insight whenever it is set.
 */
export function getNotebookAnalyzeCell(
    nodeType: NotebookNodeType,
    attributes: NotebookAnalyzeCellAttributes,
    notebookShortId: string
): NotebookAnalyzeCell | null {
    const nodeId = attributes.nodeId
    if (!nodeId) {
        return null
    }
    const shared = { notebookShortId, nodeId, nodeType, title: attributes.title || undefined }

    if (nodeType === NotebookNodeType.Query) {
        return attributes.id
            ? { ...shared, kind: 'insight', insightShortId: attributes.id }
            : { ...shared, kind: 'query', query: (attributes.query as QuerySchema | undefined) ?? undefined }
    }
    if (nodeType === NotebookNodeType.SQLV2) {
        return {
            ...shared,
            kind: 'sql',
            code: attributes.code,
            dataframeName: attributes.returnVariable || undefined,
            connectionId: attributes.connectionId ?? undefined,
        }
    }
    if (nodeType === NotebookNodeType.PythonV2) {
        return {
            ...shared,
            kind: 'python',
            code: attributes.code,
            dataframeName: attributes.returnVariable || undefined,
        }
    }
    return null
}

/** The composer prefill that opens the conversation about `cell`. */
export function getNotebookAnalyzePrompt(cell: NotebookAnalyzeCell): string {
    return CELL_KIND_PROMPTS[cell.kind]
}

export function getNotebookAnalyzeHeadline(cell: NotebookAnalyzeCell): string {
    return CELL_KIND_HEADLINES[cell.kind]
}

/**
 * What the composer pins above the textbox for `cell`, or null when the cell has nothing to preview.
 * A HogQL cell renders as a chart only when it runs against PostHog, because a chart over a direct
 * connection would query PostHog's ClickHouse instead of the connected database.
 */
export function buildNotebookAnalyzeFocus(cell: NotebookAnalyzeCell): ComposerFocus | null {
    const shared = {
        id: cell.nodeId,
        title: cell.title || CELL_KIND_LABELS[cell.kind],
        caption: NOTEBOOK_ANALYZE_FOCUS_CAPTION,
        dismissGroup: NOTEBOOK_ANALYZE_CONTEXT_GROUP,
    }

    if (cell.kind === 'insight' && cell.insightShortId) {
        return {
            ...shared,
            query: { kind: NodeKind.SavedInsightNode, shortId: cell.insightShortId as InsightShortId },
            openUrl: urls.insightView(cell.insightShortId as InsightShortId),
        }
    }
    if (cell.kind === 'query' && cell.query) {
        return { ...shared, query: cell.query }
    }
    const code = cell.code?.trim() ? cell.code : null
    if (!code) {
        return null
    }
    if (cell.kind === 'sql') {
        return cell.connectionId
            ? { ...shared, code, codeLanguage: 'sql' }
            : {
                  ...shared,
                  query: { kind: NodeKind.DataVisualizationNode, source: { kind: NodeKind.HogQLQuery, query: code } },
              }
    }
    if (cell.kind === 'python') {
        return { ...shared, code, codeLanguage: 'python' }
    }
    return null
}

export interface NotebookOutlineEntry {
    node_id: string
    cell_type: string
    title?: string
    dataframe_name?: string
    analyzed?: true
}

export interface NotebookOutline {
    cells: NotebookOutlineEntry[]
    truncated: boolean
}

const OUTLINE_TAG_CELL_TYPES: Record<string, string> = {
    Query: 'query',
    SQLV2: 'sql',
    PythonV2: 'python',
}

function propString(value: NotebookPropValue | undefined): string | undefined {
    return typeof value === 'string' && value ? value : undefined
}

/**
 * Lists the notebook's cells without their bodies, so the agent can answer "which cells feed this one"
 * without a tool call. Only component blocks with a node id count as cells; prose is left out.
 */
export function buildNotebookOutline(nodes: NotebookBlockNode[], analyzedNodeId: string): NotebookOutline {
    const cells: NotebookOutlineEntry[] = []
    for (const node of nodes) {
        if (node.type !== 'component') {
            continue
        }
        const nodeId = propString(node.props.nodeId)
        if (!nodeId) {
            continue
        }
        const isSavedInsight = node.tagName === 'Query' && !!propString(node.props.id)
        cells.push({
            node_id: nodeId,
            cell_type: isSavedInsight ? 'insight' : (OUTLINE_TAG_CELL_TYPES[node.tagName] ?? node.tagName),
            title: propString(node.props.title),
            dataframe_name: propString(node.props.returnVariable),
            ...(nodeId === analyzedNodeId ? { analyzed: true as const } : {}),
        })
    }

    if (cells.length <= NOTEBOOK_OUTLINE_CELL_CAP) {
        return { cells, truncated: false }
    }
    const half = NOTEBOOK_OUTLINE_CELL_CAP / 2
    const analyzedIndex = Math.max(
        0,
        cells.findIndex((cell) => cell.analyzed)
    )
    const start = Math.min(Math.max(0, analyzedIndex - half), cells.length - NOTEBOOK_OUTLINE_CELL_CAP)
    return { cells: cells.slice(start, start + NOTEBOOK_OUTLINE_CELL_CAP), truncated: true }
}

/**
 * The context the agent gets for one cell: a notebook ref, the cell itself, the notebook outline when
 * there is one, and the instruction that explains them. The cell body has no `key`, so dedupe runs on
 * its value and an edited cell is sent again rather than pruned as already seen.
 */
export function buildNotebookAnalyzeContext(
    cell: NotebookAnalyzeCell,
    notebookTitle: string,
    outline?: NotebookOutline
): AttachedContextItem[] {
    const body = {
        notebook_short_id: cell.notebookShortId,
        node_id: cell.nodeId,
        cell_type: cell.kind,
        title: cell.title,
        insight_short_id: cell.insightShortId,
        query: cell.query,
        code: cell.code,
        dataframe_name: cell.dataframeName,
        connection_id: cell.connectionId,
    }
    let value = JSON.stringify(body)
    if (value.length > NOTEBOOK_ANALYZE_CELL_VALUE_BUDGET) {
        value = JSON.stringify({ ...body, query: undefined, code: undefined, query_elided: true })
    }

    return [
        {
            type: 'notebook',
            key: cell.notebookShortId,
            label: notebookTitle || 'Notebook',
            dismissGroup: NOTEBOOK_ANALYZE_CONTEXT_GROUP,
        },
        {
            type: 'notebook_cell',
            label: `Cell: ${cell.title || CELL_KIND_LABELS[cell.kind]}`,
            value,
            dismissGroup: NOTEBOOK_ANALYZE_CONTEXT_GROUP,
        },
        ...(outline && outline.cells.length > 0
            ? [
                  {
                      type: 'notebook_outline',
                      hidden: true,
                      value: JSON.stringify(outline),
                      dismissGroup: NOTEBOOK_ANALYZE_CONTEXT_GROUP,
                  },
              ]
            : []),
        {
            type: 'instructions',
            hidden: true,
            value: NOTEBOOK_ANALYZE_INSTRUCTIONS,
            dismissGroup: NOTEBOOK_ANALYZE_CONTEXT_GROUP,
        },
    ]
}

/**
 * Turns an agent result into the notebook cell that holds it. A saved insight becomes a reference,
 * a HogQL query becomes an editable SQL cell where the reader can keep working on it, and everything
 * else becomes an inline query cell.
 *
 * Returns null when the result carries no query the notebook can render.
 */
export function buildNotebookCellFromArtifact(
    payload: VisualizationArtifactActionPayload,
    options: { sqlV2Enabled: boolean }
): JSONContent | null {
    const titleAttrs = payload.content.name ? { title: payload.content.name } : {}

    if (payload.insightShortId) {
        return { type: NotebookNodeType.Query, attrs: { id: payload.insightShortId, ...titleAttrs } }
    }
    if (!payload.query) {
        return null
    }

    // The same conversion a hand-written `<SQLV2 query=… />` tag goes through, so an agent-authored
    // cell keeps the chart the agent picked alongside its code.
    const sqlProps = options.sqlV2Enabled
        ? getSqlV2PropsFromQueryProp({ query: payload.query as unknown as NotebookPropValue })
        : null
    if (sqlProps?.code) {
        return {
            type: NotebookNodeType.SQLV2,
            // A parsed block id is a content fingerprint, so a cell that will be run needs a durable
            // id of its own: running it writes runId and result, which changes the fingerprint.
            attrs: { ...sqlProps, returnVariable: '', nodeId: uuid(), ...titleAttrs },
        }
    }

    return { type: NotebookNodeType.Query, attrs: { query: payload.query, ...titleAttrs } }
}
