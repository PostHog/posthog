import { ArtifactContentType, VisualizationArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'

import type { VisualizationArtifactActionPayload } from 'products/posthog_ai/frontend/api/types'

import { NotebookNodeType } from '../types'
import {
    NotebookAnalyzeCell,
    NotebookAnalyzeCellAttributes,
    NotebookAnalyzeCellKind,
    buildNotebookAnalyzeContext,
    buildNotebookCellFromArtifact,
    getNotebookAnalyzeCell,
} from './notebookAnalyzeContext'

describe('notebookAnalyzeContext', () => {
    const queryCell: NotebookAnalyzeCell = {
        notebookShortId: 'nb123',
        nodeId: 'node-1',
        kind: 'query',
        title: 'Signups',
        query: { kind: NodeKind.TrendsQuery, series: [] } as any,
    }

    const payload = (
        query: VisualizationArtifactActionPayload['query'],
        overrides: Partial<VisualizationArtifactActionPayload> = {}
    ): VisualizationArtifactActionPayload => ({
        query,
        content: {
            content_type: ArtifactContentType.Visualization,
            query: query as VisualizationArtifactContent['query'],
            name: 'Weekly signups',
            description: null,
        },
        toolName: 'query-trends',
        toolCallId: 'call-1',
        ...overrides,
    })

    it.each<[NotebookAnalyzeCellKind, NotebookAnalyzeCellAttributes, NotebookNodeType]>([
        ['insight', { nodeId: 'n', id: 'abc123' }, NotebookNodeType.Query],
        ['query', { nodeId: 'n', query: { kind: NodeKind.TrendsQuery } }, NotebookNodeType.Query],
        ['sql', { nodeId: 'n', code: 'select 1', returnVariable: 'signups' }, NotebookNodeType.SQLV2],
        ['python', { nodeId: 'n', code: 'print(1)' }, NotebookNodeType.PythonV2],
    ])('reads a %s cell from its node attributes', (kind, attributes, nodeType) => {
        expect(getNotebookAnalyzeCell(nodeType, attributes, 'nb123')).toMatchObject({
            kind,
            nodeId: 'n',
            notebookShortId: 'nb123',
        })
    })

    // The menu item's eligibility gate: everything else in a notebook has no cell to analyze, and a
    // cell with no id has nowhere to insert a result back to.
    it.each<[NotebookNodeType, NotebookAnalyzeCellAttributes]>([
        [NotebookNodeType.Recording, { nodeId: 'n', id: 'session-1' }],
        [NotebookNodeType.Query, { query: { kind: NodeKind.TrendsQuery } }],
    ])('has no analyzable cell for %s', (nodeType, attributes) => {
        expect(getNotebookAnalyzeCell(nodeType, attributes, 'nb123')).toBeNull()
    })

    it('shares one dismiss group and keeps ids out of the trusted instruction', () => {
        const items = buildNotebookAnalyzeContext(queryCell, 'Growth review')

        expect(items.map((item) => item.dismissGroup)).toEqual([
            'notebook-analyze-cell',
            'notebook-analyze-cell',
            'notebook-analyze-cell',
        ])
        expect(items.filter((item) => item.hidden).map((item) => item.type)).toEqual(['instructions'])
        // The trusted block is our own static guidance, so nothing interpolated may reach it.
        const instruction = items.find((item) => item.type === 'instructions')
        expect(instruction?.value).not.toContain('nb123')
        expect(instruction?.value).not.toContain('node-1')
    })

    it('re-sends an edited cell because the body carries no key', () => {
        const [, before] = buildNotebookAnalyzeContext(queryCell, 'Growth review')
        const [, after] = buildNotebookAnalyzeContext({ ...queryCell, title: 'Signups by plan' }, 'Growth review')

        expect(before.key).toBeUndefined()
        expect(after.value).not.toEqual(before.value)
    })

    it('elides an over-budget body and stays parseable', () => {
        const [, body] = buildNotebookAnalyzeContext({ ...queryCell, code: 'x'.repeat(20_000) }, 'Growth review')

        expect(JSON.parse(body.value ?? '')).toMatchObject({
            node_id: 'node-1',
            cell_type: 'query',
            query_elided: true,
        })
        expect(body.value).not.toContain('xxxx')
    })

    it('references a saved insight rather than copying its query', () => {
        const cell = buildNotebookCellFromArtifact(
            payload({ kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery } } as any, {
                insightShortId: 'abc123',
            }),
            { sqlV2Enabled: true }
        )

        expect(cell).toEqual({
            type: NotebookNodeType.Query,
            attrs: { id: 'abc123', title: 'Weekly signups' },
        })
    })

    it('turns a HogQL result into an editable SQL cell with a durable node id', () => {
        const cell = buildNotebookCellFromArtifact(
            payload({
                kind: NodeKind.DataVisualizationNode,
                source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
            } as any),
            { sqlV2Enabled: true }
        )

        expect(cell?.type).toBe(NotebookNodeType.SQLV2)
        expect(cell?.attrs).toMatchObject({ code: 'select 1', returnVariable: '', title: 'Weekly signups' })
        expect(typeof cell?.attrs?.nodeId).toBe('string')
    })

    it.each<[string, Record<string, unknown>, boolean]>([
        ['an insight query', { kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery } }, true],
        [
            'HogQL without the SQL cell',
            { kind: NodeKind.DataVisualizationNode, source: { kind: NodeKind.HogQLQuery, query: 'select 1' } },
            false,
        ],
    ])('falls back to an inline query cell for %s', (_name, query, sqlV2Enabled) => {
        const cell = buildNotebookCellFromArtifact(payload(query as any), { sqlV2Enabled })

        expect(cell).toEqual({
            type: NotebookNodeType.Query,
            attrs: { query, title: 'Weekly signups' },
        })
    })

    it('has no cell to build when the result carries no query', () => {
        expect(buildNotebookCellFromArtifact(payload(null), { sqlV2Enabled: true })).toBeNull()
    })
})
