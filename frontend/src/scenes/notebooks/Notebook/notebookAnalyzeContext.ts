import type { NotebookPropValue } from 'lib/components/MarkdownNotebook/types'
import type { JSONContent } from 'lib/components/RichContentEditor/types'
import { uuid } from 'lib/utils/dom'

import type { QuerySchema } from '~/queries/schema/schema-general'

import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'
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

const NOTEBOOK_ANALYZE_INSTRUCTIONS =
    'The user is looking at one cell of a PostHog notebook and is asking about it. The attached ' +
    'notebook_cell item is that cell: `node_id` identifies it inside the notebook, `cell_type` is one of ' +
    'insight, query, sql or python, and the body arrives as `insight_short_id`, `query` (an insight query ' +
    'schema) or `code` (HogQL for a sql cell, Python for a python cell). `dataframe_name` is the name later ' +
    'cells use to reference this cell. When `query_elided` is true the body was too large to attach, so ' +
    'read the cell with the notebooks-get tool. ' +
    'Use notebooks-list-frames and notebooks-get when the question needs the cells around this one. ' +
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

/**
 * The context the agent gets for one cell: a notebook ref, the cell itself, and the instruction that
 * explains both. The cell body has no `key`, so dedupe runs on its value and an edited cell is sent
 * again rather than pruned as already seen.
 */
export function buildNotebookAnalyzeContext(cell: NotebookAnalyzeCell, notebookTitle: string): AttachedContextItem[] {
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
