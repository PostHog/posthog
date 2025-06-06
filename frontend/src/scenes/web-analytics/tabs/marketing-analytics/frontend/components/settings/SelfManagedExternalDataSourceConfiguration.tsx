import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import {
    DataWarehouseSourceIcon,
    mapUrlToProvider,
    mapUrlToSourceName,
} from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { ExternalDataSource, ManualLinkSourceType, PipelineNodeTab, PipelineStage } from '~/types'

import {
    SharedExternalDataSourceConfiguration,
    SimpleDataWarehouseTable,
} from './SharedExternalDataSourceConfiguration'

const VALID_MANUAL_LINK_SOURCES: ManualLinkSourceType[] = ['aws', 'google-cloud', 'cloudflare-r2', 'azure']

// This is to map tables that are self-managed by the user.
// It's a workaround to allow users to map columns to the correct fields in the Marketing Analytics product.
export function SelfManagedExternalDataSourceConfiguration(): JSX.Element {
    const { dataWarehouseSources, selfManagedTables } = useValues(dataWarehouseSettingsLogic)
    const { toggleManualLinkFormVisible, setManualLinkingProvider } = useActions(sourceWizardLogic)

    const tables: SimpleDataWarehouseTable[] = selfManagedTables
        .map((source) => ({
            ...source,
            id: source.id,
            source_type: mapUrlToSourceName(source.url_pattern) as ExternalDataSource['source_type'],
            source_id: source.id,
            source_prefix: '',
            name: source.name,
            columns: Object.keys(source.fields).map((field) => ({
                name: source.fields[field].hogql_value,
                type: source.fields[field].type,
            })),
            url_pattern: source.url_pattern,
            sourceUrl: urls.pipelineNode(
                PipelineStage.Source,
                `self-managed-${source.id}`,
                PipelineNodeTab.SourceConfiguration
            ),
        }))
        .flat()

    const handleSourceAdd = (manualLinkSource: ManualLinkSourceType): void => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
        toggleManualLinkFormVisible(true)
        setManualLinkingProvider(manualLinkSource)
    }

    return (
        <SharedExternalDataSourceConfiguration
            title="Self-managed Data Warehouse Sources Configuration"
            description="PostHog can display marketing data in our Marketing Analytics product from the following self-managed data warehouse sources."
            tables={tables}
            loading={dataWarehouseSources === null}
            validSources={VALID_MANUAL_LINK_SOURCES}
            renderSourceIcon={renderSourceIcon}
            onSourceAdd={handleSourceAdd}
        />
    )
}

const renderSourceIcon = (item: SimpleDataWarehouseTable): JSX.Element => (
    <DataWarehouseSourceIcon type={mapUrlToProvider(item.url_pattern!)} />
)
