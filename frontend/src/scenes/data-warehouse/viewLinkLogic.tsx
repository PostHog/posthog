import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DataWarehouseViewLink } from '~/types'

import { dataWarehouseSavedQueriesLogic } from './saved_queries/dataWarehouseSavedQueriesLogic'
import { DataWarehouseSceneRow } from './types'
import type { viewLinkLogicType } from './viewLinkLogicType'
import { ViewLinkKeyLabel } from './ViewLinkModal'

const NEW_VIEW_LINK: DataWarehouseViewLink = {
    id: 'new',
    saved_query_id: undefined,
    table: undefined,
    to_join_key: undefined,
    from_join_key: undefined,
}

export interface KeySelectOption {
    value: string
    label: JSX.Element
}

export const viewLinkLogic = kea<viewLinkLogicType>([
    path(['scenes', 'data-warehouse', 'viewLinkLogic']),
    connect({
        values: [dataWarehouseSavedQueriesLogic, ['savedQueries'], databaseTableListLogic, ['tableOptions']],
        actions: [databaseTableListLogic, ['loadDatabase']],
    }),
    actions({
        selectView: (selectedView) => ({ selectedView }),
        setView: (view) => ({ view }),
        selectTableName: (selectedTableName: string) => ({ selectedTableName }),
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
        selectedTableName: [
            null as string | null,
            {
                selectTableName: (_, { selectedTableName }) => selectedTableName,
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
            errors: ({ saved_query_id, to_join_key, from_join_key }) => {
                let to_join_key_err: string | undefined = undefined
                let from_join_key_err: string | undefined = undefined

                if (!to_join_key) {
                    to_join_key_err = 'Must select a join key'
                }

                if (!from_join_key) {
                    from_join_key_err = 'Must select a join key'
                }

                if (
                    to_join_key &&
                    from_join_key &&
                    values.mappedToJoinKeyOptions[to_join_key]?.type !==
                        values.mappedFromJoinKeyOptions[from_join_key]?.type
                ) {
                    to_join_key_err = 'Join key types must match'
                    from_join_key_err = 'Join key types must match'
                }

                return {
                    saved_query_id: !saved_query_id ? 'Must select a view' : undefined,
                    to_join_key: to_join_key_err,
                    from_join_key: from_join_key_err,
                }
            },
            submit: async ({ saved_query_id, to_join_key, from_join_key }) => {
                if (values.selectedTable) {
                    await api.dataWarehouseViewLinks.create({
                        table: values.selectedTable.name,
                        saved_query_id,
                        to_join_key,
                        from_join_key,
                    })
                    actions.toggleFieldModal()
                    // actions.loadDatabase()
                    // actions.loadViewLinks()
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
        selectedTable: [
            (s) => [s.selectedTableName, s.tableOptions],
            (selectedTableName: string, tableOptions: DataWarehouseSceneRow[]) =>
                tableOptions.find((row) => row.name === selectedTableName),
        ],
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
            (selectedView: DataWarehouseSceneRow | null): KeySelectOption[] => {
                if (!selectedView) {
                    return []
                }
                return selectedView.columns.map((column) => ({
                    value: column.key,
                    label: <ViewLinkKeyLabel column={column} />,
                }))
            },
        ],
        mappedToJoinKeyOptions: [
            (s) => [s.selectedView],
            (selectedView: DataWarehouseSceneRow | null) => {
                if (!selectedView) {
                    return []
                }
                return selectedView.columns.reduce((acc, column) => {
                    acc[column.key] = column
                    return acc
                }, {})
            },
        ],
        fromJoinKeyOptions: [
            (s) => [s.selectedTable],
            (selectedTable: DataWarehouseSceneRow | null): KeySelectOption[] => {
                if (!selectedTable) {
                    return []
                }
                return selectedTable.columns
                    .filter((column) => column.type !== 'view')
                    .map((column) => ({
                        value: column.key,
                        label: <ViewLinkKeyLabel column={column} />,
                    }))
            },
        ],
        mappedFromJoinKeyOptions: [
            (s) => [s.selectedTable],
            (selectedTable: DataWarehouseSceneRow | null) => {
                if (!selectedTable) {
                    return []
                }
                return selectedTable.columns.reduce((acc, column) => {
                    acc[column.key] = column
                    return acc
                }, {})
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadViewLinks()
    }),
])
