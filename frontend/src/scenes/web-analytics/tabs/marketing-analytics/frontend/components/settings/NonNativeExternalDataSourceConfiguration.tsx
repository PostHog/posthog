import { useValues } from 'kea'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { ExternalDataSource } from '~/types'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    SharedExternalDataSourceConfiguration,
    SimpleDataWarehouseTable,
} from './SharedExternalDataSourceConfiguration'

const VALID_MARKETING_SOURCES: ExternalDataSource['source_type'][] = ['BigQuery']

// This is to map tables that are not natively integrated with PostHog.
// It's a workaround to allow users to map columns to the correct fields in the Marketing Analytics product.
// An example of native integration is the Google Ads integration.
export function NonNativeExternalDataSourceConfiguration({
    buttonRef,
}: {
    buttonRef?: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { dataWarehouseSources } = useValues(marketingAnalyticsSettingsLogic)

    const marketingSources =
        dataWarehouseSources?.results.filter((source) => VALID_MARKETING_SOURCES.includes(source.source_type)) ?? []

    const tables: SimpleDataWarehouseTable[] = marketingSources
        .map((source) =>
            source.schemas.map((schema) => ({
                ...schema,
                source_type: source.source_type,
                source_id: source.id,
                source_prefix: source.prefix,
                columns: schema.table?.columns || [],
            }))
        )
        .flat()

    return (
        <SharedExternalDataSourceConfiguration
            title="Non Native Data Warehouse Sources Configuration"
            description="PostHog can display marketing data in our Marketing Analytics product from the following data warehouse sources."
            tables={tables}
            loading={dataWarehouseSources === null}
            buttonRef={buttonRef}
            renderSourceIcon={renderSourceIcon}
        />
    )
}

const renderSourceIcon = (item: SimpleDataWarehouseTable): JSX.Element => (
    <DataWarehouseSourceIcon type={item.source_type} />
)
