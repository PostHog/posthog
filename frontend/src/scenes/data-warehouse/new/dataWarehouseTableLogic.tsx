import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import { DataTableNode } from '~/queries/schema'
import { AnyPropertyFilter, DataWarehouseTable } from '~/types'

import type { dataWarehouseTableLogicType } from './dataWarehouseTableLogicType'

export interface TableLogicProps {
    /** A UUID or 'new'. */
    id: string
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
}

export const dataWarehouseTableLogic = kea<dataWarehouseTableLogicType>([
    path(['scenes', 'data-warehouse', 'tableLogic']),
    props({} as TableLogicProps),
    connect(() => ({
        actions: [databaseTableListLogic, ['loadDatabase']],
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
    forms(({ actions, props }) => ({
        table: {
            defaults: { ...NEW_WAREHOUSE_TABLE } as DataWarehouseTable,
            errors: ({ name, url_pattern, credential, format }) => {
                if (url_pattern?.startsWith('s3://')) {
                    return {
                        url_pattern:
                            'Please use the https version of your bucket url e.g. https://your-org.s3.amazonaws.com/airbyte/stripe/invoices/*.pqt',
                    }
                }

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
])
