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
import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { OutputTab, outputPaneLogic } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'

import { DataVisualizationNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
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
    useNotebookCodeSQLEditorSync,
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

// Stands in for sqlEditorLogic: the code sync reads `queryInput` plus the connection selectors,
// and the connection selector's only contract with it is `setSourceQuery`. The two selectors
// mirror the real ones so the stub can't quietly diverge on the raw-mode rule.
const stubSqlEditorLogic = kea<any>([
    path(['test', 'stubSqlEditorLogic']),
    props({} as { tabId: string }),
    key((logicProps: { tabId: string }) => logicProps.tabId),
    actions({
        initialize: true,
        setQueryInput: (...args: any[]) => ({ queryInput: args[0] as string | null }),
        setSourceQuery: (...args: any[]) => ({ sourceQuery: args[0] as DataVisualizationNode }),
    }),
    reducers({
        queryInput: [null as string | null, { setQueryInput: (_: any, { queryInput }: any) => queryInput }],
        sourceQuery: [
            {
                kind: NodeKind.DataVisualizationNode,
                source: { kind: NodeKind.HogQLQuery, query: '' },
                display: ChartDisplayType.ActionsTable,
            } as DataVisualizationNode,
            { setSourceQuery: (_: any, { sourceQuery }: any) => sourceQuery },
        ],
    }),
    selectors({
        selectedConnectionId: [
            (s: any) => [s.sourceQuery],
            (sourceQuery: DataVisualizationNode) => sourceQuery.source.connectionId,
        ],
        sendRawQueryEnabled: [
            (s: any) => [s.sourceQuery, s.selectedConnectionId],
            (sourceQuery: DataVisualizationNode, selectedConnectionId: string | undefined) =>
                !!selectedConnectionId && (sourceQuery.source.sendRawQuery ?? false),
        ],
    }),
])

function CodeSyncHarness({
    code,
    connectionId,
    sendRawQuery,
    tabId,
    updateAttributes,
}: {
    code: string
    connectionId?: string | null
    sendRawQuery?: boolean | null
    tabId: string
    updateAttributes: jest.Mock
}): JSX.Element | null {
    useNotebookCodeSQLEditorSync({
        attributes: { nodeId: 'node-1', code, connectionId, sendRawQuery },
        tabId,
        updateAttributes,
        persistConnection: true,
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

    it('keeps the selected connection while the code cell is edited', async () => {
        // The bug: every keystroke rebuilt the source query from scratch, dropping the connection
        // the user had picked — so the selector snapped back to PostHog mid-typing.
        initKeaTests()
        const tabId = 'notebook-sql-connection-keystroke'
        const logic = stubSqlEditorLogic({ tabId })
        ;(sqlEditorLogic as unknown as jest.Mock).mockImplementation(() => logic)
        const updateAttributes = jest.fn()

        render(
            <CodeSyncHarness code="select 1" connectionId="conn-1" tabId={tabId} updateAttributes={updateAttributes} />
        )
        await waitFor(() => expect(logic.values.sourceQuery.source.connectionId).toBe('conn-1'))

        act(() => {
            logic.actions.setQueryInput('select 2')
        })

        await waitFor(() => expect(updateAttributes).toHaveBeenCalledWith({ code: 'select 2' }))
        expect(logic.values.sourceQuery.source.connectionId).toBe('conn-1')
    })

    it('persists a newly picked connection onto the cell', async () => {
        // The connection selector writes straight into sqlEditorLogic, so without this the choice
        // would never reach the run request or survive a reload.
        initKeaTests()
        const tabId = 'notebook-sql-connection-persist'
        const logic = stubSqlEditorLogic({ tabId })
        ;(sqlEditorLogic as unknown as jest.Mock).mockImplementation(() => logic)
        const updateAttributes = jest.fn()

        render(<CodeSyncHarness code="select 1" tabId={tabId} updateAttributes={updateAttributes} />)
        await waitFor(() => expect(logic.values.queryInput).toBe('select 1'))

        act(() => {
            logic.actions.setSourceQuery({
                ...logic.values.sourceQuery,
                source: { ...logic.values.sourceQuery.source, connectionId: 'conn-1', sendRawQuery: true },
            })
        })

        await waitFor(() =>
            expect(updateAttributes).toHaveBeenCalledWith({ connectionId: 'conn-1', sendRawQuery: true })
        )
    })
})
