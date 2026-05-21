import { renderHook } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { useNotebookCodeSQLEditorSync, useNotebookQuerySQLEditorSync } from './NotebookSQLEditor'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('scenes/data-warehouse/editor/SQLEditor', () => ({
    SQLEditor: () => null,
    SQLEditorPanel: {
        Output: 'output',
        Query: 'query',
    },
}))

jest.mock('scenes/data-warehouse/editor/sqlEditorLogic', () => ({
    sqlEditorLogic: jest.fn((props) => ({ type: 'sqlEditorLogic', props })),
}))

const mockedUseActions = useActions as jest.Mock
const mockedUseValues = useValues as jest.Mock
const mockedSqlEditorLogic = sqlEditorLogic as jest.Mock

const setQueryInput = jest.fn()
const setSourceQuery = jest.fn()
const updateAttributes = jest.fn()
const initialize = jest.fn()
const runQuery = jest.fn()

let queryInput: string | null
let sourceQuery: DataVisualizationNode

function buildSourceQuery(query: string): DataVisualizationNode {
    return {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query,
        },
        display: ChartDisplayType.ActionsTable,
    }
}

describe('NotebookSQLEditor sync hooks', () => {
    beforeEach(() => {
        queryInput = 'select old'
        sourceQuery = buildSourceQuery('select old')

        mockedUseValues.mockImplementation(() => ({ queryInput, sourceQuery }))
        mockedUseActions.mockImplementation(() => ({ initialize, runQuery, setQueryInput, setSourceQuery }))
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    it('seeds code-node SQL on initial mount without writing attributes', () => {
        queryInput = null
        sourceQuery = buildSourceQuery('')

        renderHook(() =>
            useNotebookCodeSQLEditorSync({
                attributes: { nodeId: 'node-1', code: 'select old' },
                updateAttributes,
                tabId: 'tab-1',
            })
        )

        expect(setQueryInput).toHaveBeenCalledWith('select old')
        expect(setSourceQuery).toHaveBeenCalledWith(buildSourceQuery('select old'))
        expect(updateAttributes).not.toHaveBeenCalled()
    })

    it('syncs code-node SQL from changed attributes without writing stale SQL back', () => {
        const { rerender } = renderHook(
            ({ code }) =>
                useNotebookCodeSQLEditorSync({
                    attributes: { nodeId: 'node-1', code },
                    updateAttributes,
                    tabId: 'tab-1',
                }),
            {
                initialProps: { code: 'select old' },
            }
        )

        expect(setQueryInput).not.toHaveBeenCalled()
        expect(updateAttributes).not.toHaveBeenCalled()

        rerender({ code: 'select remote' })

        expect(setQueryInput).toHaveBeenCalledWith('select remote')
        expect(setSourceQuery).toHaveBeenCalledWith(buildSourceQuery('select remote'))
        expect(updateAttributes).not.toHaveBeenCalled()
        expect(mockedSqlEditorLogic).toHaveBeenCalledWith({ tabId: 'tab-1', mode: SQLEditorMode.Embedded })
    })

    it('writes local code-node SQL edits back to attributes', () => {
        const { rerender } = renderHook(() =>
            useNotebookCodeSQLEditorSync({
                attributes: { nodeId: 'node-1', code: 'select old' },
                updateAttributes,
                tabId: 'tab-1',
            })
        )

        queryInput = 'select local'
        rerender()

        expect(updateAttributes).toHaveBeenCalledWith({ code: 'select local' })
        expect(setSourceQuery).toHaveBeenCalledWith(buildSourceQuery('select local'))
    })

    it('ignores equal query-node attribute rerenders', () => {
        const { rerender } = renderHook(
            ({ query }) =>
                useNotebookQuerySQLEditorSync({
                    attributes: { nodeId: 'node-1', query },
                    updateAttributes,
                    tabId: 'tab-1',
                }),
            {
                initialProps: { query: buildSourceQuery('select old') },
            }
        )

        jest.clearAllMocks()
        rerender({ query: buildSourceQuery('select old') })

        expect(setQueryInput).not.toHaveBeenCalled()
        expect(setSourceQuery).not.toHaveBeenCalled()
        expect(updateAttributes).not.toHaveBeenCalled()
    })

    it('syncs query-node SQL from changed attributes without writing stale SQL back', () => {
        const { rerender } = renderHook(
            ({ query }) =>
                useNotebookQuerySQLEditorSync({
                    attributes: { nodeId: 'node-1', query },
                    updateAttributes,
                    tabId: 'tab-1',
                }),
            {
                initialProps: { query: buildSourceQuery('select old') },
            }
        )

        const remoteQuery = buildSourceQuery('select remote')
        rerender({ query: remoteQuery })

        expect(setQueryInput).toHaveBeenCalledWith('select remote')
        expect(setSourceQuery).toHaveBeenCalledWith(remoteQuery)
        expect(runQuery).not.toHaveBeenCalled()
        expect(updateAttributes).not.toHaveBeenCalled()
    })

    it('writes local query-node SQL edits back to attributes', () => {
        const { rerender } = renderHook(() =>
            useNotebookQuerySQLEditorSync({
                attributes: { nodeId: 'node-1', query: buildSourceQuery('select old') },
                updateAttributes,
                tabId: 'tab-1',
            })
        )

        queryInput = 'select local'
        sourceQuery = buildSourceQuery('select local')
        rerender()

        expect(updateAttributes).toHaveBeenCalledWith({ query: buildSourceQuery('select local') })
    })
})
