import { useValues } from 'kea'
import { router } from 'kea-router'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { ExternalDataSource, PipelineNodeTab, PipelineStage } from '~/types'

import {
    SharedExternalDataSourceConfiguration,
    SimpleDataWarehouseTable,
} from './SharedExternalDataSourceConfiguration'

const VALID_MARKETING_SOURCES: ExternalDataSource['source_type'][] = ['BigQuery']

const transformSourcesIntoTables = (sources: any[]): SimpleDataWarehouseTable[] => {
    return sources
        .map((source) =>
            source.schemas.map((schema: any) => ({
                ...schema,
                source_type: source.source_type,
                source_id: source.id,
                source_prefix: source.prefix,
                columns: schema.table?.columns || [],
                sourceUrl: urls.pipelineNode(PipelineStage.Source, `managed-${source.id}`, PipelineNodeTab.Schemas),
            }))
        )
        .flat()
}

// This is to map tables that are not natively integrated with PostHog.
// It's a workaround to allow users to map columns to the correct fields in the Marketing Analytics product.
// An example of native integration is the Google Ads integration.
export function NonNativeExternalDataSourceConfiguration(): JSX.Element {
    const { dataWarehouseSources } = useValues(dataWarehouseSettingsLogic)

    const marketingSources =
        dataWarehouseSources?.results.filter((source) => VALID_MARKETING_SOURCES.includes(source.source_type)) ?? []

    const tables: SimpleDataWarehouseTable[] = transformSourcesIntoTables(marketingSources)

    const handleSourceAdd = (source: ExternalDataSource['source_type']): void => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source, { source }))
    }

    return (
        <SharedExternalDataSourceConfiguration
            title="Non Native Data Warehouse Sources Configuration"
            description="PostHog can display marketing data in our Marketing Analytics product from the following data warehouse sources."
            tables={tables}
            loading={dataWarehouseSources === null}
            validSources={VALID_MARKETING_SOURCES}
            renderSourceIcon={renderSourceIcon}
            onSourceAdd={handleSourceAdd}
        />
    )
}

const renderSourceIcon = (item: SimpleDataWarehouseTable): JSX.Element => (
    <DataWarehouseSourceIcon type={item.source_type} />
)
