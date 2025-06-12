import { connect, kea, path, selectors } from 'kea'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { DatabaseSchemaDataWarehouseTable, SourceMap } from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab, PipelineNodeTab, PipelineStage } from '~/types'

import { MARKETING_ANALYTICS_SCHEMA } from '../../utils'
import type { marketingAnalyticsLogicType } from './marketingAnalyticsLogicType'
import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'

export type ExternalTable = {
    name: string
    source_type: string
    id: string
    source_map_id: string
    source_prefix: string
    columns: { name: string; type: string }[]
    url_pattern: string
    sourceUrl: string
    external_type: DataWarehouseSettingsTab
    source_map: SourceMap | null
    schema_name: string
}

export const marketingAnalyticsLogic = kea<marketingAnalyticsLogicType>([
    path(['scenes', 'web-analytics', 'marketingAnalyticsLogic']),
    connect(() => ({
        values: [
            marketingAnalyticsSettingsLogic,
            ['sources_map'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseTables', 'dataWarehouseSourcesLoading', 'dataWarehouseSources'],
        ],
    })),
    selectors({
        validSourcesMap: [
            (s) => [s.sources_map],
            (sources_map) => {
                if (!sources_map || Object.keys(sources_map).length === 0) {
                    return null
                }

                const validSourcesMap = sources_map

                Object.keys(MARKETING_ANALYTICS_SCHEMA)
                    .filter((column_name: string) => MARKETING_ANALYTICS_SCHEMA[column_name].required)
                    .forEach((column_name: string) => {
                        Object.entries(validSourcesMap).forEach(([tableId, fieldMapping]: [string, any]) => {
                            if (!fieldMapping[column_name]) {
                                delete validSourcesMap[tableId]
                            }
                        })
                    })

                if (Object.keys(validSourcesMap).length === 0) {
                    return null
                }

                return validSourcesMap
            },
        ],
        externalTables: [
            (s) => [s.dataWarehouseTables, s.sources_map, s.dataWarehouseSources],
            (dataWarehouseTables: DatabaseSchemaDataWarehouseTable[], sources_map, dataWarehouseSources) => {
                const externalTables: ExternalTable[] = []
                if (dataWarehouseTables?.length) {
                    dataWarehouseTables.forEach((table) => {
                        if (!table.fields) {
                            return
                        }
                        const dataWarehouseSource = dataWarehouseSources?.results.find((source: any) =>
                            source.schemas
                                .map((schema: DatabaseSchemaDataWarehouseTable) => schema.id)
                                .includes(table.schema?.id)
                        )
                        const isDataWarehouse = !!table.schema
                        const tableType = isDataWarehouse
                            ? DataWarehouseSettingsTab.Managed
                            : DataWarehouseSettingsTab.SelfManaged
                        const sourceMap = sources_map?.[table.schema?.id || ''] ?? sources_map?.[table.id] ?? null

                        externalTables.push({
                            ...table,
                            name: table.name,
                            source_type: table.source?.source_type || mapUrlToProvider(table.url_pattern),
                            source_map_id: table.schema?.id || table.source?.id || table.id,
                            source_prefix: table.source?.prefix || '',
                            columns: Object.keys(table.fields).map((field) => ({
                                name: table.fields[field].hogql_value,
                                type: table.fields[field].type,
                            })),
                            sourceUrl: urls.pipelineNode(
                                PipelineStage.Source,
                                `${tableType}-${dataWarehouseSource?.id || table.source?.id || table.id}`,
                                isDataWarehouse ? PipelineNodeTab.Schemas : PipelineNodeTab.SourceConfiguration
                            ),
                            external_type: tableType,
                            source_map: sourceMap,
                            schema_name: table.schema?.name || table.name,
                        })
                    })
                }

                return externalTables
            },
        ],
        validExternalTables: [
            (s) => [s.externalTables, s.sources_map],
            (externalTables: ExternalTable[], sources_map: SourceMap): ExternalTable[] => {
                const validSourcesMap = sources_map ?? {}
                Object.keys(MARKETING_ANALYTICS_SCHEMA)
                    .filter((column_name: string) => MARKETING_ANALYTICS_SCHEMA[column_name].required)
                    .forEach((column_name: string) => {
                        Object.entries(validSourcesMap).forEach(([tableId, fieldMapping]: [string, any]) => {
                            if (!fieldMapping[column_name]) {
                                delete validSourcesMap[tableId]
                            }
                        })
                    })

                if (Object.keys(validSourcesMap).length === 0) {
                    return []
                }

                return externalTables.filter((table) => validSourcesMap[table.source_map_id])
            },
        ],
        loading: [
            (s) => [s.dataWarehouseSourcesLoading],
            (dataWarehouseSourcesLoading: boolean) => dataWarehouseSourcesLoading,
        ],
    }),
])
