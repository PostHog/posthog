import { actions, kea, path, reducers, selectors } from 'kea'
import { TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'

import { DatabaseSchemaDataWarehouseTable, DatabaseSchemaTable } from '~/queries/schema'
import { DataWarehouseSavedQuery } from '~/types'

import type { editorSceneLogicType } from './editorSceneLogicType'

export const editorSceneLogic = kea<editorSceneLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'editorSceneLogic']),
    actions({
        setSidebarOverlayOpen: (isOpen: boolean) => ({ isOpen }),
        selectSchema: (schema: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery) => ({
            schema,
        }),
    }),
    reducers({
        sidebarOverlayOpen: [
            false,
            {
                setSidebarOverlayOpen: (_, { isOpen }) => isOpen,
                selectSchema: (_, { schema }) => schema !== null,
            },
        ],
        selectedSchema: [
            null as DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null,
            {
                selectSchema: (_, { schema }) => schema,
            },
        ],
    }),
    selectors({
        sidebarOverlayTreeItems: [
            (s) => [s.selectedSchema],
            (selectedSchema): TreeItem[] => {
                if (selectedSchema === null) {
                    return []
                }
                if ('fields' in selectedSchema) {
                    return Object.values(selectedSchema.fields).map((field) => ({
                        name: field.name,
                        type: field.type,
                    }))
                }

                if ('columns' in selectedSchema) {
                    return Object.values(selectedSchema.columns).map((column) => ({
                        name: column.name,
                        type: column.type,
                    }))
                }
                return []
            },
        ],
    }),
])
