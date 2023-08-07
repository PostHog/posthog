import { lemonToast } from '@posthog/lemon-ui'
import { kea, path, props, key, listeners, afterMount, reducers, actions, selectors, connect } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import { AnyPropertyFilter, Breadcrumb, DataWarehouseTable } from '~/types'
import { DataTableNode } from '~/queries/schema'
import { databaseSceneLogic } from 'scenes/data-management/database/databaseSceneLogic'
import type { dataWarehouseTableLogicType } from './dataWarehouseTableLogicType'

export interface TableLogicProps {
    id: string | 'new'
}

const NEW_WAREHOUSE_TABLE: DataWarehouseTable = {
    id: '',
    name: '',
    url_pattern: '',
    format: 'Parquet',
    credential: {
        access_key: '',
        access_secret: '',
    },
    columns: [],
}

export const dataWarehouseTableLogic = kea<dataWarehouseTableLogicType>([
    path(['scenes', 'data-warehouse', 'tableLogic']),
    props({} as TableLogicProps),
    key(({ id }) => id),
    connect(() => ({
        actions: [databaseSceneLogic, ['loadDatabase']],
    })),
    actions({
        editingTable: (editing: boolean) => ({ editing }),
        updateTargetingFlagFilters: (index: number, properties: AnyPropertyFilter[]) => ({ index, properties }),
        addConditionSet: true,
        removeConditionSet: (index: number) => ({ index }),
        launchTable: true,
        stopTable: true,
        archiveTable: true,
        setDataTableQuery: (query: DataTableNode) => ({ query }),
    }),
    loaders(({ props }) => ({
        table: {
            loadTable: async () => {
                if (props.id && props.id !== 'new') {
                    return await api.dataWarehouseTables.get(props.id)
                }
                return { ...NEW_WAREHOUSE_TABLE }
            },
            createTable: async (tablePayload) => {
                return await api.dataWarehouseTables.create({
                    ...tablePayload,
                })
            },
            updateTable: async (tablePayload) => {
                return await api.dataWarehouseTables.update(props.id, tablePayload)
            },
        },
    })),
    listeners(({ actions }) => ({
        createTableSuccess: async ({ table }) => {
            lemonToast.success(<>Table {table.name} created</>)
            actions.loadDatabase()
            router.actions.replace(urls.dataWarehouse())
        },
        updateTableSuccess: async ({ table }) => {
            lemonToast.success(<>Table {table.name} updated</>)
            actions.editingTable(false)
            router.actions.replace(urls.dataWarehouse())
        },
    })),
    reducers({
        isEditingTable: [
            false,
            {
                editingTable: (_, { editing }) => editing,
            },
        ],
        dataTableQuery: [
            null as DataTableNode | null,
            {
                setDataTableQuery: (_, { query }) => query,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.table],
            (table: DataWarehouseTable): Breadcrumb[] => [
                {
                    name: 'Tables',
                    path: urls.dataWarehouse(),
                },
                ...(table?.name ? [{ name: table.name }] : []),
            ],
        ],
    }),
    forms(({ actions, props }) => ({
        table: {
            defaults: { ...NEW_WAREHOUSE_TABLE } as DataWarehouseTable,
            errors: ({ name, url_pattern, credential, format }) => {
                return {
                    name: !name && 'Please enter a name.',
                    url_pattern: !url_pattern && 'Please enter a url pattern.',
                    credential: {
                        access_secret: !credential.access_secret && 'Please enter an access secret.',
                        access_key: !credential.access_key && 'Please enter an access key.',
                    },
                    format: !format && 'Please enter the format of your files.',
                }
            },
            submit: async (tablePayload) => {
                if (props.id && props.id !== 'new') {
                    actions.updateTable(tablePayload)
                } else {
                    actions.createTable(tablePayload)
                }
            },
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.dataWarehouseTable(props.id ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadTable()
                } else {
                    actions.resetTable()
                }
            }
        },
    })),
    afterMount(async ({ props, actions }) => {
        // if (props.id !== 'new') {
        //     await actions.loadTable()
        // }
        if (props.id === 'new') {
            actions.resetTable()
        }
    }),
])
