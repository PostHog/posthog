import { actions, connect, kea, selectors, listeners, reducers, path } from 'kea'
import { dataWarehouseSavedQueriesLogic } from './saved_queries/dataWarehouseSavedQueriesLogic'
import { DataWarehouseSceneRow } from './types'
import { viewLinkLogicType } from './viewLinkLogicType'
import { DataWarehouseViewLink } from '~/types'
import { forms } from 'kea-forms'
import api from 'lib/api'

const NEW_VIEW_LINK: DataWarehouseViewLink = {
    id: 'new',
    saved_query_id: undefined,
    table: undefined,
    to_join_key: undefined,
    from_join_key: undefined,
}

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
        saveViewLink: (viewLink) => ({ viewLink }),
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
    forms(({ actions, values }) => ({
        viewLink: {
            defaults: NEW_VIEW_LINK,
            errors: ({ saved_query_id, to_join_key, from_join_key }) => ({
                saved_query_id: !saved_query_id ? 'Must select a view' : undefined,
                to_join_key: !to_join_key ? 'Must select a join key' : undefined,
                from_join_key: !from_join_key ? 'Must select a join key' : undefined,
            }),
            submit: ({ saved_query_id, to_join_key, from_join_key }) => {
                if (values.selectedTable) {
                    api.dataWarehouseViewLinks.create({
                        table: values.selectedTable.name,
                        saved_query_id,
                        to_join_key,
                        from_join_key,
                    })
                    actions.toggleFieldModal()
                }
            },
        },
    })),
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
