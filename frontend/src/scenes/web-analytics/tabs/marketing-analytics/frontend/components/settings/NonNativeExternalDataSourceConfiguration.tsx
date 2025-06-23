import { useValues } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

import { ExternalDataSource, PipelineStage } from '~/types'

import { ExternalTable, marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { NonNativeMarketingSource, VALID_NON_NATIVE_MARKETING_SOURCES } from '../../logic/utils'
import { SharedExternalDataSourceConfiguration } from './SharedExternalDataSourceConfiguration'

// This allows users to map columns from data warehouse sources (BigQuery, Postgres, etc.)
// to the correct fields in the Marketing Analytics product.
// These sources don't have predefined schemas like native integrations, so users need to manually map their columns.
export function NonNativeExternalDataSourceConfiguration(): JSX.Element {
    const { externalTables, loading } = useValues(marketingAnalyticsLogic)

    const tables: ExternalTable[] = externalTables.filter((source) =>
        VALID_NON_NATIVE_MARKETING_SOURCES.includes(source.source_type as NonNativeMarketingSource)
    )
    const handleSourceAdd = (source: ExternalDataSource['source_type']): void => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source, { source }))
    }

    return (
        <SharedExternalDataSourceConfiguration<ExternalDataSource['source_type']>
            title="Non Native Data Warehouse Sources Configuration"
            description="Configure data warehouse sources to display marketing analytics in PostHog. You'll need to map the required columns for each table to enable the functionality."
            tables={tables}
            loading={loading}
            validSources={VALID_NON_NATIVE_MARKETING_SOURCES}
            onSourceAdd={handleSourceAdd}
        />
    )
}
