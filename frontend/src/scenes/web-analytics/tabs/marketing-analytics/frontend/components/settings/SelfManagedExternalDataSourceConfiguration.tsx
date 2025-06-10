import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { urls } from 'scenes/urls'

import { ManualLinkSourceType, PipelineStage } from '~/types'

import { ExternalTable, marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { SharedExternalDataSourceConfiguration } from './SharedExternalDataSourceConfiguration'

const VALID_MANUAL_LINK_SOURCES: ManualLinkSourceType[] = ['aws', 'google-cloud', 'cloudflare-r2', 'azure']

// This allows users to map columns from self-managed data warehouse sources (AWS, GCP, etc.)
// to the correct fields in the Marketing Analytics product.
// These sources don't have predefined schemas like native integrations, so users need to manually map their columns.
export function SelfManagedExternalDataSourceConfiguration(): JSX.Element {
    const { externalTables, loading } = useValues(marketingAnalyticsLogic)
    const { toggleManualLinkFormVisible, setManualLinkingProvider } = useActions(sourceWizardLogic)

    const tables: ExternalTable[] | null =
        externalTables.filter((source) =>
            VALID_MANUAL_LINK_SOURCES.includes(source.source_type as ManualLinkSourceType)
        ) ?? null

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
            loading={loading}
            validSources={VALID_MANUAL_LINK_SOURCES}
            onSourceAdd={handleSourceAdd}
        />
    )
}
