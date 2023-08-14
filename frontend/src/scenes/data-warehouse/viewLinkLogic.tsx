import { actions, connect, kea, selectors, listeners, reducers, path, afterMount } from 'kea'
import { dataWarehouseSavedQueriesLogic } from './saved_queries/dataWarehouseSavedQueriesLogic'
import { DataWarehouseSceneRow } from './types'
import { DataWarehouseViewLink } from '~/types'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { databaseSceneLogic } from 'scenes/data-management/database/databaseSceneLogic'
import { loaders } from 'kea-loaders'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { viewLinkLogicType } from './viewLinkLogicType'

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
        actions: [databaseSceneLogic, ['loadDatabase']],
    }),
    actions({
        selectView: (selectedView) => ({ selectedView }),
        setView: (view) => ({ view }),
        selectTable: (selectedTable) => ({ selectedTable }),
        toggleFieldModal: true,
        saveViewLink: (viewLink) => ({ viewLink }),
        deleteViewLink: (table, column) => ({ table, column }),
    }),
    loaders({
        viewLinks: {
            __default: [] as DataWarehouseViewLink[],
            loadViewLinks: async () => {
                const response = await api.dataWarehouseViewLinks.list()
                return response.results
            },
        },
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
            submit: async ({ saved_query_id, to_join_key, from_join_key }) => {
                if (values.selectedTable) {
                    await api.dataWarehouseViewLinks.create({
                        table: values.selectedTable.name,
                        saved_query_id,
                        to_join_key,
                        from_join_key,
                    })
                    actions.toggleFieldModal()
                    actions.loadDatabase()
                }
            },
        },
    })),
    listeners(({ values, actions }) => ({
        selectView: ({ selectedView }) => {
            actions.setView(values.mappedViewOptions[selectedView])
        },
        deleteViewLink: async ({ table, column }) => {
            const matchedSavedQuery = values.savedQueries.find((savedQuery) => {
                return savedQuery.name === column
            })
            const matchedViewLink = values.viewLinks.find((viewLink) => {
                return viewLink.table === table && matchedSavedQuery && matchedSavedQuery.id === viewLink.saved_query
            })
            if (!matchedViewLink) {
                lemonToast.error(`Error deleting view link`)
                return
            }
            await api.dataWarehouseViewLinks.delete(matchedViewLink.id)
            actions.loadDatabase()
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
    afterMount(({ actions }) => {
        actions.loadViewLinks()
    }),
])
