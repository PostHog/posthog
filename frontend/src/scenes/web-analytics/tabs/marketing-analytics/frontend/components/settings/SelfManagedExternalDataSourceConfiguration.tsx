import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { urls } from 'scenes/urls'

import { ManualLinkSourceType, PipelineStage } from '~/types'

import { ExternalTable, marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { VALID_SELF_MANAGED_MARKETING_SOURCES } from '../../logic/utils'
import { SharedExternalDataSourceConfiguration } from './SharedExternalDataSourceConfiguration'

// This allows users to map columns from self-managed data warehouse sources (AWS, GCP, etc.)
// to the correct fields in the Marketing Analytics product.
// These sources don't have predefined schemas like native integrations, so users need to manually map their columns.
export function SelfManagedExternalDataSourceConfiguration(): JSX.Element {
    const { externalTables, loading } = useValues(marketingAnalyticsLogic)
    const { toggleManualLinkFormVisible, setManualLinkingProvider } = useActions(sourceWizardLogic)

    const tables: ExternalTable[] = externalTables.filter((source) =>
        VALID_SELF_MANAGED_MARKETING_SOURCES.includes(source.source_type as ManualLinkSourceType)
    )

    const handleSourceAdd = (manualLinkSource: ManualLinkSourceType): void => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
        toggleManualLinkFormVisible(true)
        setManualLinkingProvider(manualLinkSource)
    }

    return (
        <SharedExternalDataSourceConfiguration<ManualLinkSourceType>
            title="Self-managed data warehouse sources configuration"
            description="Configure self-managed data warehouse sources to display marketing analytics in PostHog. You'll need to map the required columns for each table to enable the functionality."
            tables={tables}
            loading={loading}
            validSources={VALID_SELF_MANAGED_MARKETING_SOURCES}
            onSourceAdd={handleSourceAdd}
        />
    )
}
