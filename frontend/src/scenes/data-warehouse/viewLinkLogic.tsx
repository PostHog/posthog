import { actions, connect, kea, selectors, listeners, reducers, path } from 'kea'
import { dataWarehouseSavedQueriesLogic } from './saved_queries/dataWarehouseSavedQueriesLogic'
import { DataWarehouseSceneRow } from './types'
import { viewLinkLogicType } from './viewLinkLogicType'

export const viewLinkLogic = kea<viewLinkLogicType>([
    path(['scenes', 'data-warehouse', 'viewLinkLogic']),
    connect({
        values: [dataWarehouseSavedQueriesLogic, ['savedQueries']],
    }),
    actions({
        selectView: (selectedView) => ({ selectedView }),
        setView: (view) => ({ view }),
        selectTable: (selectedTable) => ({ selectedTable }),
        toggleFieldModal: true,
    }),
    reducers({
        selectedView: [
            null as DataWarehouseSceneRow | null,
            {
                setView: (_, { view }) => view,
            },
        ],
        selectedTable: [
            null as DataWarehouseSceneRow | null,
            {
                selectTable: (_, { selectedTable }) => selectedTable,
            },
        ],
        isFieldModalOpen: [
            false,
            {
                toggleFieldModal: (state) => !state,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        selectView: ({ selectedView }) => {
            actions.setView(values.mappedViewOptions[selectedView])
        },
    })),
    selectors({
        viewOptions: [
            (s) => [s.savedQueries],
            (savedQueries: DataWarehouseSceneRow[]) =>
                savedQueries.map((savedQuery: DataWarehouseSceneRow) => ({
                    value: savedQuery.id,
                    label: savedQuery.name,
                })),
        ],
        mappedViewOptions: [
            (s) => [s.savedQueries],
            (savedQueries: DataWarehouseSceneRow[]) =>
                savedQueries.reduce((acc, savedQuery: DataWarehouseSceneRow) => {
                    acc[savedQuery.id] = savedQuery
                    return acc
                }, {}),
        ],
        toJoinKeyOptions: [
            (s) => [s.selectedView],
            (selectedView: DataWarehouseSceneRow | null) => {
                if (!selectedView) {
                    return []
                }
                return selectedView.columns.map((column) => ({
                    value: column.key,
                    label: column.key,
                }))
            },
        ],
        fromJoinKeyOptions: [
            (s) => [s.selectedTable],
            (selectedTable: DataWarehouseSceneRow | null) => {
                if (!selectedTable) {
                    return []
                }
                return selectedTable.columns.map((column) => ({
                    value: column.key,
                    label: column.key,
                }))
            },
        ],
    }),
])
