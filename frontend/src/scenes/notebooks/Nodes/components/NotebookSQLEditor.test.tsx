jest.mock('scenes/data-warehouse/editor/SQLEditor', () => ({
    SQLEditor: () => null,
    SQLEditorPanel: {
        Output: 'output',
    },
}))

jest.mock('scenes/data-warehouse/editor/sqlEditorLogic', () => ({
    sqlEditorLogic: jest.fn(),
}))

import { NodeKind, ProductKey } from '@posthog/query-frontend/schema/schema-general'

import { ChartDisplayType } from '~/types'

import {
    EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT,
    EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT,
    EMBEDDED_SQL_EDITOR_EDIT_MIN_HEIGHT,
    EMBEDDED_SQL_EDITOR_MIN_HEIGHT,
    getEmbeddedSqlEditorStyle,
    getSqlEditorSourceQuery,
    hasAlreadyRunSqlEditorSourceQuery,
} from './NotebookSQLEditor'

describe('NotebookSQLEditor', () => {
    it('adds notebook query tags to HogQL source queries', () => {
        const sourceQuery = getSqlEditorSourceQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select 1',
        })

        expect(sourceQuery).toEqual({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select 1',
                tags: {
                    productKey: ProductKey.NOTEBOOKS,
                    scene: 'Notebook',
                },
            },
            display: ChartDisplayType.ActionsTable,
        })
    })

    it('preserves existing HogQL query tags', () => {
        const sourceQuery = getSqlEditorSourceQuery({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select 1',
                tags: {
                    name: 'custom_query',
                    productKey: ProductKey.DATA_WAREHOUSE,
                    scene: 'SQLEditor',
                },
            },
            display: ChartDisplayType.ActionsLineGraph,
        })

        expect(sourceQuery?.source.tags).toEqual({
            name: 'custom_query',
            productKey: ProductKey.DATA_WAREHOUSE,
            scene: 'SQLEditor',
        })
    })

    it('uses a concrete embedded editor height by default', () => {
        expect(EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT).toBe(333)
        expect(getEmbeddedSqlEditorStyle(undefined)).toEqual({
            height: EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT,
            minHeight: EMBEDDED_SQL_EDITOR_MIN_HEIGHT,
        })
    })

    it('uses a shorter embedded editor height for edit panels', () => {
        expect(EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT).toBe(150)
        expect(EMBEDDED_SQL_EDITOR_EDIT_MIN_HEIGHT).toBe(150)
        expect(
            getEmbeddedSqlEditorStyle(
                undefined,
                EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT,
                EMBEDDED_SQL_EDITOR_EDIT_MIN_HEIGHT
            )
        ).toEqual({
            height: EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT,
            minHeight: EMBEDDED_SQL_EDITOR_EDIT_MIN_HEIGHT,
        })
    })

    it('preserves a custom embedded editor height', () => {
        expect(getEmbeddedSqlEditorStyle(320)).toEqual({
            height: 320,
            minHeight: EMBEDDED_SQL_EDITOR_MIN_HEIGHT,
        })
    })

    it('treats an already-run SQL source as current when only tags differ', () => {
        const sourceQuery = getSqlEditorSourceQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select 1',
        })

        expect(sourceQuery).not.toBeNull()

        const lastRunQuery = {
            ...sourceQuery!,
            source: {
                ...sourceQuery!.source,
                tags: {
                    productKey: ProductKey.DATA_WAREHOUSE,
                    scene: 'SQLEditor',
                },
            },
        }

        expect(hasAlreadyRunSqlEditorSourceQuery(sourceQuery!, lastRunQuery)).toBe(true)
    })

    it('normalizes no-op raw-query flags when checking already-run SQL sources', () => {
        const sourceQuery = getSqlEditorSourceQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select 1',
            sendRawQuery: false,
        })
        const lastRunQuery = getSqlEditorSourceQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select 1',
        })

        expect(sourceQuery).not.toBeNull()
        expect(lastRunQuery).not.toBeNull()
        expect(hasAlreadyRunSqlEditorSourceQuery(sourceQuery!, lastRunQuery)).toBe(true)
    })

    it('does not treat a changed SQL source as already run', () => {
        const sourceQuery = getSqlEditorSourceQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select 1',
        })
        const lastRunQuery = getSqlEditorSourceQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select 2',
        })

        expect(sourceQuery).not.toBeNull()
        expect(lastRunQuery).not.toBeNull()
        expect(hasAlreadyRunSqlEditorSourceQuery(sourceQuery!, lastRunQuery)).toBe(false)
    })
})
