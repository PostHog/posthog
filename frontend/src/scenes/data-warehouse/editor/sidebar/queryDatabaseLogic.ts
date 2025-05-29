import { LemonMenuItem, lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import { TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaTable,
} from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery, DataWarehouseViewLink } from '~/types'

import { dataWarehouseJoinsLogic } from '../../external/dataWarehouseJoinsLogic'
import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { viewLinkLogic } from '../../viewLinkLogic'
import type { queryDatabaseLogicType } from './queryDatabaseLogicType'

const isDataWarehouseTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaDataWarehouseTable => {
    return 'type' in table && table.type === 'data_warehouse'
}

const isPostHogTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaTable => {
    return 'type' in table && table.type === 'posthog'
}

const isViewTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DataWarehouseSavedQuery => {
    return 'query' in table
}

const isJoined = (field: DatabaseSchemaField): boolean => {
    return field.type === 'view' || field.type === 'lazy_table'
}

export const queryDatabaseLogic = kea<queryDatabaseLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'queryDatabaseLogic']),
    actions({
        selectSchema: (schema: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery) => ({
            schema,
        }),
    }),
    connect(() => ({
        values: [
            dataWarehouseJoinsLogic,
            ['joins', 'joinsLoading'],
            databaseTableListLogic,
            ['posthogTablesMap', 'dataWarehouseTablesMap'],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueryMapById'],
        ],
        actions: [
            viewLinkLogic,
            ['toggleEditJoinModal'],
            databaseTableListLogic,
            ['loadDatabase'],
            dataWarehouseJoinsLogic,
            ['loadJoins'],
        ],
    })),
    reducers({
        selectedSchema: [
            null as DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null,
            {
                selectSchema: (_, { schema }) => schema,
            },
        ],
    }),
    selectors(({ actions }) => ({
        sidebarOverlayTreeItems: [
            (s) => [
                s.selectedSchema,
                s.joins,
                s.posthogTablesMap,
                s.dataWarehouseTablesMap,
                s.dataWarehouseSavedQueryMapById,
            ],
            (
                selectedSchema,
                joins,
                posthogTablesMap,
                dataWarehouseTablesMap,
                dataWarehouseSavedQueryMapById
            ): TreeItem[] => {
                if (selectedSchema === null) {
                    return []
                }
                let table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null =
                    null
                if (isPostHogTable(selectedSchema)) {
                    table = posthogTablesMap[selectedSchema.name]
                } else if (isDataWarehouseTable(selectedSchema)) {
                    table = dataWarehouseTablesMap[selectedSchema.name]
                } else if (isViewTable(selectedSchema)) {
                    table = dataWarehouseSavedQueryMapById[selectedSchema.id]
                }

                if (table == null) {
                    return []
                }

                const relevantJoins = joins.filter((join) => join.source_table_name === table!.name)
                const joinsByFieldName = relevantJoins.reduce((acc, join) => {
                    if (join.field_name) {
                        acc[join.field_name] = join
                    }
                    return acc
                }, {} as Record<string, DataWarehouseViewLink>)

                const menuItems = (field: DatabaseSchemaField): LemonMenuItem[] => {
                    return isJoined(field) && joinsByFieldName[field.name]
                        ? [
                              {
                                  label: 'Edit',
                                  onClick: () => {
                                      actions.toggleEditJoinModal(joinsByFieldName[field.name])
                                  },
                              },
                              {
                                  label: 'Delete join',
                                  status: 'danger',
                                  onClick: () => {
                                      const join = joinsByFieldName[field.name]
                                      void deleteWithUndo({
                                          endpoint: api.dataWarehouseViewLinks.determineDeleteEndpoint(),
                                          object: {
                                              id: join.id,
                                              name: `${join.field_name} on ${join.source_table_name}`,
                                          },
                                          callback: () => {
                                              actions.loadDatabase()
                                              actions.loadJoins()
                                          },
                                      }).catch((e) => {
                                          lemonToast.error(`Failed to delete warehouse view link: ${e.detail}`)
                                      })
                                  },
                              },
                          ]
                        : []
                }

                if ('fields' in table) {
                    return Object.values(table.fields).map((field) => ({
                        name: field.name,
                        type: field.type,
                        menuItems: menuItems(field),
                    }))
                }

                if ('columns' in table) {
                    return Object.values(table.columns).map((column) => ({
                        name: column.name,
                        type: column.type,
                        menuItems: menuItems(column),
                    }))
                }
                return []
            },
        ],
    })),
])
