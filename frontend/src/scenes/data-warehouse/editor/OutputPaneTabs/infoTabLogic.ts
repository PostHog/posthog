import { connect, kea, key, path, props, selectors } from 'kea'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { multitabEditorLogic } from '../multitabEditorLogic'
import type { infoTabLogicType } from './infoTabLogicType'

export interface InfoTableRow {
    name: string
    type: 'source' | 'table'
    status?: string
    last_run_at?: string
}

export interface InfoTabLogicProps {
    codeEditorKey: string
}

export const infoTabLogic = kea<infoTabLogicType>([
    path(['data-warehouse', 'editor', 'outputPaneTabs', 'infoTabLogic']),
    props({} as InfoTabLogicProps),
    key((props) => props.codeEditorKey),
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
            (s) => [s.metadata, s.dataWarehouseSavedQueryMap],
            (metadata, dataWarehouseSavedQueryMap) => {
                if (!metadata) {
                    return []
                }
                return (
                    metadata.table_names?.map((table_name) => {
                        const view = dataWarehouseSavedQueryMap[table_name]
                        if (view) {
                            return {
                                name: table_name,
                                type: 'table',
                                status: view.status,
                                last_run_at: view.last_run_at || 'never',
                            }
                        }

                        return {
                            name: table_name,
                            type: 'source',
                            status: undefined,
                            last_run_at: undefined,
                        }
                    }) || []
                )
            },
        ],
    }),
])
