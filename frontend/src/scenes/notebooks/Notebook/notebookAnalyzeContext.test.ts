import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'

import { ArtifactContentType, VisualizationArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'

import type { VisualizationArtifactActionPayload } from 'products/posthog_ai/frontend/api/types'

import { NotebookNodeType } from '../types'
import {
    NOTEBOOK_OUTLINE_CELL_CAP,
    NotebookAnalyzeCell,
    NotebookAnalyzeCellAttributes,
    NotebookAnalyzeCellKind,
    buildNotebookAnalyzeContext,
    buildNotebookAnalyzeFocus,
    buildNotebookCellFromArtifact,
    buildNotebookOutline,
    getNotebookAnalyzeCell,
} from './notebookAnalyzeContext'

describe('notebookAnalyzeContext', () => {
    const queryCell: NotebookAnalyzeCell = {
        notebookShortId: 'nb123',
        nodeId: 'node-1',
        nodeType: NotebookNodeType.Query,
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

    const cellOf = (overrides: Partial<NotebookAnalyzeCell>): NotebookAnalyzeCell => ({
        ...queryCell,
        query: undefined,
        ...overrides,
    })

    it.each<[string, NotebookAnalyzeCell, Record<string, unknown> | null]>([
        [
            'charts a saved insight and links to it',
            cellOf({ kind: 'insight', insightShortId: 'abc123' }),
            {
                query: { kind: NodeKind.SavedInsightNode, shortId: 'abc123' },
                openUrl: expect.stringContaining('/insights/abc123'),
            },
        ],
        ['charts an inline query', cellOf({ kind: 'query', query: queryCell.query }), { query: queryCell.query }],
        [
            'charts a HogQL cell that runs against PostHog',
            cellOf({ kind: 'sql', code: 'select 1' }),
            {
                query: {
                    kind: NodeKind.DataVisualizationNode,
                    source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
                },
            },
        ],
        [
            'shows the SQL of a direct-connection cell instead of charting it against PostHog',
            cellOf({ kind: 'sql', code: 'select 1', connectionId: 'conn-1' }),
            { code: 'select 1', codeLanguage: 'sql' },
        ],
        [
            'shows the code of a Python cell',
            cellOf({ kind: 'python', code: 'print(1)' }),
            { code: 'print(1)', codeLanguage: 'python' },
        ],
    ])('focus: %s', (_name, cell, expected) => {
        expect(buildNotebookAnalyzeFocus(cell)).toMatchObject({
            id: 'node-1',
            dismissGroup: 'notebook-analyze-cell',
            ...expected,
        })
    })

    it('pins nothing for a Python cell with no code', () => {
        expect(buildNotebookAnalyzeFocus(cellOf({ kind: 'python', code: '  ' }))).toBeNull()
    })

    const componentNode = (
        nodeId: string,
        tagName = 'SQLV2',
        props: Record<string, string> = {}
    ): NotebookBlockNode => ({
        id: `block-${nodeId}`,
        type: 'component',
        tagName,
        props: { nodeId, ...props },
    })

    it('outlines cells in order without bodies, marking the analyzed one', () => {
        const outline = buildNotebookOutline(
            [
                { id: 'p', type: 'paragraph', children: [] } as NotebookBlockNode,
                componentNode('a', 'SQLV2', { code: 'select 1', returnVariable: 'signups', title: 'Signups' }),
                componentNode('b', 'Query', { id: 'abc123' }),
                componentNode('c', 'PythonV2', { code: 'print(1)' }),
            ],
            'c'
        )

        expect(outline).toEqual({
            truncated: false,
            cells: [
                { node_id: 'a', cell_type: 'sql', title: 'Signups', dataframe_name: 'signups' },
                { node_id: 'b', cell_type: 'insight' },
                { node_id: 'c', cell_type: 'python', analyzed: true },
            ],
        })
        expect(JSON.stringify(outline)).not.toContain('select 1')
    })

    it.each([
        ['near the start', 5],
        ['in the middle', 100],
        ['near the end', 198],
    ])('keeps the analyzed cell when the outline is capped, analyzed %s', (_name, analyzedIndex) => {
        const nodes = Array.from({ length: 200 }, (_, index) => componentNode(`n${index}`))

        const outline = buildNotebookOutline(nodes, `n${analyzedIndex}`)

        expect(outline.truncated).toBe(true)
        expect(outline.cells).toHaveLength(NOTEBOOK_OUTLINE_CELL_CAP)
        expect(outline.cells.some((cell) => cell.node_id === `n${analyzedIndex}` && cell.analyzed)).toBe(true)
    })

    it('attaches the outline hidden and in the same dismiss group', () => {
        const items = buildNotebookAnalyzeContext(queryCell, 'Growth review', {
            cells: [{ node_id: 'node-1', cell_type: 'query', analyzed: true }],
            truncated: false,
        })

        const outline = items.find((item) => item.type === 'notebook_outline')
        expect(outline).toMatchObject({ hidden: true, dismissGroup: 'notebook-analyze-cell' })
        // The outline carries notebook data, so it must stay out of the trusted instruction block.
        expect(items.find((item) => item.type === 'instructions')?.value).not.toContain('node-1')
    })
})
