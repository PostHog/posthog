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

export const getTableEventName = (surveyName: string): string => {
    return `${surveyName} survey sent`
}

export interface TableLogicProps {
    id: string | 'new'
}

export type NewTable = Pick<DataWarehouseTable, 'name' | 'url_pattern' | 'credential'>

const NEW_TABLE: NewTable = {
    name: '',
    url_pattern: '',
    credential: {
        access_key: '',
        access_secret: '',
    },
}

export const tableLogic = kea<surveyLogicType>([
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
                return { ...NEW_TABLE }
            },
            createTable: async (tablePayload) => {
                return await api.dataWarehouseTables.create({
                    ...tablePayload,
                    credential: {
                        access_key: tablePayload.access_key,
                        access_secret: tablePayload.access_secret,
                    },
                })
            },
            updateTable: async (tablePayload) => {
                return await api.dataWarehouseTables.update(props.id, tablePayload)
            },
        },
    })),
    listeners(({ actions }) => ({
        createTableSuccess: async ({ survey }) => {
            lemonToast.success(<>Table {survey.name} created</>)
            actions.loadTables()
            router.actions.replace(urls.survey(survey.id))
        },
        updateTableSuccess: async ({ survey }) => {
            lemonToast.success(<>Table {survey.name} updated</>)
            actions.editingTable(false)
            router.actions.replace(urls.survey(survey.id))
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
            defaults: { ...NEW_TABLE } as DataWarehouseTable,
            errors: ({ name, url_pattern, access_key, access_secret, type }) => ({
                name: !name && 'Please enter a name.',
                url_pattern: !url_pattern && 'Please enter a url pattern.',
                access_secret: !access_secret && 'Please enter an access secret.',
                access_key: !access_key && 'Please enter an access key.',
                type: !type && 'Please enter an access key.',
            }),
            submit: async (surveyPayload) => {
                if (props.id && props.id !== 'new') {
                    actions.updateTable(surveyPayload)
                } else {
                    actions.createTable(surveyPayload)
                }
            },
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.survey(props.id ?? 'new')]: (_, __, ___, { method }) => {
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
        if (props.id !== 'new') {
            await actions.loadTable()
        }
        if (props.id === 'new') {
            actions.resetTable()
        }
    }),
])
