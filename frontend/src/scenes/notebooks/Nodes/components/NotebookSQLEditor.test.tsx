jest.mock('scenes/data-warehouse/editor/SQLEditor', () => ({
    SQLEditor: () => null,
    SQLEditorPanel: {
        Output: 'output',
    },
}))

jest.mock('scenes/data-warehouse/editor/sqlEditorLogic', () => ({
    sqlEditorLogic: jest.fn(),
}))

import { act, render, waitFor } from '@testing-library/react'

import { OutputTab, outputPaneLogic } from 'scenes/data-warehouse/editor/outputPaneLogic'

import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import {
    EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT,
    EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT,
    EMBEDDED_SQL_EDITOR_EDIT_MIN_HEIGHT,
    EMBEDDED_SQL_EDITOR_MIN_HEIGHT,
    getEmbeddedSqlEditorStyle,
    getNotebookSqlEditorOutputTab,
    getSqlEditorSourceQuery,
    hasAlreadyRunSqlEditorSourceQuery,
    useNotebookSQLOutputTabSync,
} from './NotebookSQLEditor'

function OutputTabSyncHarness({
    outputTab,
    tabId,
    updateAttributes,
}: {
    outputTab?: OutputTab | null
    tabId: string
    updateAttributes: jest.Mock
}): JSX.Element | null {
    useNotebookSQLOutputTabSync({
        attributes: {
            nodeId: 'node-1',
            outputTab,
        },
        tabId,
        updateAttributes,
    })

    return null
}

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

    it('normalizes persisted embedded output tabs', () => {
        expect(getNotebookSqlEditorOutputTab(OutputTab.Visualization)).toBe(OutputTab.Visualization)
        expect(getNotebookSqlEditorOutputTab(OutputTab.Both)).toBe(OutputTab.Both)
        expect(getNotebookSqlEditorOutputTab(undefined)).toBe(OutputTab.Results)
        expect(getNotebookSqlEditorOutputTab('invalid')).toBe(OutputTab.Results)
    })

    it('persists embedded output tab changes to notebook node attributes', async () => {
        initKeaTests()
        const tabId = 'notebook-sql-output-tab-sync'
        const updateAttributes = jest.fn()

        render(<OutputTabSyncHarness outputTab={OutputTab.Results} tabId={tabId} updateAttributes={updateAttributes} />)

        await waitFor(() => expect(outputPaneLogic({ tabId }).values.activeTab).toBe(OutputTab.Results))

        act(() => {
            outputPaneLogic({ tabId }).actions.setActiveTab(OutputTab.Visualization)
        })

        await waitFor(() => expect(updateAttributes).toHaveBeenCalledWith({ outputTab: OutputTab.Visualization }))
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
