jest.mock('scenes/data-warehouse/editor/SQLEditor', () => ({
    SQLEditor: () => null,
    SQLEditorPanel: {
        Output: 'output',
    },
}))

jest.mock('scenes/data-warehouse/editor/sqlEditorLogic', () => ({
    sqlEditorLogic: jest.fn(),
}))

import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { getSqlEditorSourceQuery } from './NotebookSQLEditor'

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
})
