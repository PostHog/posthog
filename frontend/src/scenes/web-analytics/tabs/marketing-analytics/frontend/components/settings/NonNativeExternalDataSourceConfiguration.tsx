import { useValues } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

import { ExternalDataSource, PipelineStage } from '~/types'

import { ExternalTable, marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { SharedExternalDataSourceConfiguration } from './SharedExternalDataSourceConfiguration'

const VALID_MARKETING_SOURCES: ExternalDataSource['source_type'][] = ['BigQuery']

// This allows users to map columns from data warehouse sources (BigQuery, Postgres, etc.)
// to the correct fields in the Marketing Analytics product.
// These sources don't have predefined schemas like native integrations, so users need to manually map their columns.
export function NonNativeExternalDataSourceConfiguration(): JSX.Element {
    const { externalTables, loading } = useValues(marketingAnalyticsLogic)

    const tables: ExternalTable[] | null =
        externalTables.filter((source) =>
            VALID_MARKETING_SOURCES.includes(source.source_type as ExternalDataSource['source_type'])
        ) ?? null
    const handleSourceAdd = (source: ExternalDataSource['source_type']): void => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source, { source }))
    }

    return (
        <SharedExternalDataSourceConfiguration<ExternalDataSource['source_type']>
            title="Non Native Data Warehouse Sources Configuration"
            description="Configure data warehouse sources to display marketing analytics in PostHog. You'll need to map the required columns for each table to enable the functionality."
            tables={tables}
            loading={loading}
            validSources={VALID_MARKETING_SOURCES}
            onSourceAdd={handleSourceAdd}
        />
    )
}
