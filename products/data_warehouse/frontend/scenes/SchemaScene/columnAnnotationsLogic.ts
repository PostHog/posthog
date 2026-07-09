import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    warehouseColumnAnnotationsCreate,
    warehouseColumnAnnotationsList,
    warehouseColumnAnnotationsPartialUpdate,
} from 'products/data_warehouse/frontend/generated/api'
import { WarehouseColumnAnnotationApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import type { columnAnnotationsLogicType } from './columnAnnotationsLogicType'

export interface ColumnAnnotationsLogicProps {
    tableId: string
}

export const columnAnnotationsLogic = kea<columnAnnotationsLogicType>([
    props({} as ColumnAnnotationsLogicProps),
    key(({ tableId }) => tableId),
    path((key) => ['products', 'dataWarehouse', 'columnAnnotationsLogic', key]),
    actions({
        saveDescription: (columnName: string, description: string) => ({ columnName, description }),
        setSavingColumn: (columnName: string | null) => ({ columnName }),
    }),
    loaders(({ props }) => ({
        annotations: [
            [] as WarehouseColumnAnnotationApi[],
            {
                loadAnnotations: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const response = await warehouseColumnAnnotationsList(String(teamId), {
                        table_id: props.tableId,
                    })
                    return response.results
                },
            },
        ],
    })),
    reducers({
        savingColumn: [
            null as string | null,
            {
                setSavingColumn: (_, { columnName }) => columnName,
            },
        ],
    }),
    selectors({
        annotationByColumn: [
            (s) => [s.annotations],
            (annotations): Record<string, WarehouseColumnAnnotationApi> =>
                Object.fromEntries(annotations.map((annotation) => [annotation.column_name, annotation])),
        ],
    }),
    listeners(({ props, actions, values }) => ({
        saveDescription: async ({ columnName, description }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            actions.setSavingColumn(columnName)
            const existing = values.annotationByColumn[columnName]
            try {
                if (existing) {
                    await warehouseColumnAnnotationsPartialUpdate(String(teamId), existing.id, { description })
                } else {
                    await warehouseColumnAnnotationsCreate(String(teamId), {
                        table: props.tableId,
                        column_name: columnName,
                        description,
                    } as WarehouseColumnAnnotationApi)
                }
                lemonToast.success('Description saved')
                actions.loadAnnotations()
            } catch (e: any) {
                lemonToast.error(e?.message || "Can't save description at this time")
            } finally {
                actions.setSavingColumn(null)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAnnotations()
    }),
])
