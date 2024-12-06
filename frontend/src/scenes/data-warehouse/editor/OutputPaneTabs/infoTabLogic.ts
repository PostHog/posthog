import { connect, kea, path, props, selectors } from 'kea'

import { multitabEditorLogic } from '../multitabEditorLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import type { infoTabLogicType } from './infoTabLogicType'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

export interface InfoTableRow {
    name: string
    type: string
}

interface InfoTabLogicProps {
    codeEditorKey: string
}

export const infoTabLogic = kea<infoTabLogicType>([
    path(['data-warehouse', 'editor', 'outputPaneTabs', 'infoTabLogic']),
    props({} as InfoTabLogicProps),
    connect((props: InfoTabLogicProps) => ({
        values: [
            multitabEditorLogic({ key: props.codeEditorKey }),
            ['metadata'],
            databaseTableListLogic,
            ['posthogTablesMap', 'dataWarehouseTablesMap'],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueryMap'],
        ],
    })),
    selectors({
        sourceTableItems: [
            (s) => [s.metadata, s.dataWarehouseTablesMap, s.posthogTablesMap, s.dataWarehouseSavedQueryMap],
            (metadata, dataWarehouseTablesMap, posthogTablesMap, dataWarehouseSavedQueryMap) => {
                if (!metadata) {
                    return []
                }
                return metadata.table_names.map((table_name) => {
                    let table = dataWarehouseSavedQueryMap[table_name]
                    if (table) {
                        return {
                            name: table_name,
                            type: 'table',
                            status: table.status,
                            last_run_at: table.last_run_at || 'never',
                        }
                    }

                    table = dataWarehouseTablesMap[table_name] || posthogTablesMap[table_name]
                    return {
                        name: table_name,
                        type: 'source',
                        status: undefined,
                        last_run_at: undefined,
                    }
                })
            },
        ],
    }),
])
