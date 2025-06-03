import { useValues } from 'kea'
import {
    DataWarehouseSourceIcon,
    mapUrlToProvider,
    mapUrlToSourceName,
} from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { ExternalDataSource } from '~/types'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    SharedExternalDataSourceConfiguration,
    SimpleDataWarehouseTable,
} from './SharedExternalDataSourceConfiguration'

// This is to map tables that are self-managed by the user.
// It's a workaround to allow users to map columns to the correct fields in the Marketing Analytics product.
export function SelfManagedExternalDataSourceConfiguration({
    buttonRef,
}: {
    buttonRef?: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { dataWarehouseSources, selfManagedTables } = useValues(marketingAnalyticsSettingsLogic)
    const marketingSources = selfManagedTables ?? []

    const tables: SimpleDataWarehouseTable[] = marketingSources
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
        }))
        .flat()

    return (
        <SharedExternalDataSourceConfiguration
            title="Self-managed Data Warehouse Sources Configuration"
            description="PostHog can display marketing data in our Marketing Analytics product from the following self-managed data warehouse sources."
            tables={tables}
            loading={dataWarehouseSources === null}
            buttonRef={buttonRef}
            renderSourceIcon={renderSourceIcon}
        />
    )
}

const renderSourceIcon = (item: SimpleDataWarehouseTable): JSX.Element => (
    <DataWarehouseSourceIcon type={mapUrlToProvider(item.url_pattern!)} />
)
