import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ExternalDataSchemaStatus } from '~/types'

import { SourceSetupPanel } from 'products/marketing_analytics/frontend/dashboard/SourceSetupPanel'

import { MarketingSourceStatus, marketingAnalyticsLogic } from '../logic/marketingAnalyticsLogic'
import { nativeSourceDisplayLabel } from '../logic/utils'

export const MarketingAnalyticsSourceStatusBanner = ({
    hiddenSourceIds = [],
}: {
    hiddenSourceIds?: string[]
}): JSX.Element | null => {
    const { allAvailableSourcesWithStatus, sourceValidationError } = useValues(marketingAnalyticsLogic)

    const sourcesWithIssues = allAvailableSourcesWithStatus
        .filter((source) => !hiddenSourceIds.includes(source.id))
        // Routine incremental syncs set Running too, and the panel's syncing copy is about the first sync.
        .filter(
            (source) =>
                source.status === 'Failed' ||
                source.status === 'Paused' ||
                source.status === 'Cancelled' ||
                source.status === MarketingSourceStatus.Error ||
                source.status === MarketingSourceStatus.Warning
        )

    if (sourcesWithIssues.length === 0 && !sourceValidationError) {
        return null
    }

    return (
        <div className="mb-2">
            {sourceValidationError && (
                <LemonBanner type="warning" className="mt-4">
                    Could not check source configuration. Reload the dashboard to try again.
                </LemonBanner>
            )}
            {sourcesWithIssues.length > 0 && (
                <SourceSetupPanel
                    state="waiting"
                    compact
                    showIllustration={false}
                    manageSourceDataAttr="marketing-source-status-settings"
                    expansionKey="source-status"
                    title="Some connections need attention"
                    description="Fix these connections to keep your spend data up to date."
                    connections={sourcesWithIssues.map((source) => ({
                        id: source.id,
                        name:
                            source.type === 'native'
                                ? source.prefix ||
                                  `${nativeSourceDisplayLabel(source.source_type)} (${source.id.slice(0, 8)})`
                                : source.name,
                        sourceType: source.source_type,
                        status:
                            source.status === ExternalDataSchemaStatus.Failed ||
                            source.status === MarketingSourceStatus.Error
                                ? 'Sync failed'
                                : 'Needs attention',
                        detail: source.statusMessage,
                        manageUrl:
                            source.type === 'native'
                                ? urls.dataWarehouseSource(`managed-${source.id}`)
                                : urls.settings('environment-marketing-analytics'),
                    }))}
                />
            )}
        </div>
    )
}
