import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import { ExternalDataSchemaStatus } from '~/types'

import { MarketingSourceStatus, marketingAnalyticsLogic } from '../logic/marketingAnalyticsLogic'
import { nativeSourceDisplayLabel } from '../logic/utils'

export const MarketingAnalyticsSourceStatusBanner = (): JSX.Element | null => {
    const { allAvailableSourcesWithStatus, sourceValidationError } = useValues(marketingAnalyticsLogic)

    const sourcesWithIssues = allAvailableSourcesWithStatus.filter(
        (source) =>
            source.status === 'Running' ||
            source.status === 'Failed' ||
            source.status === 'Paused' ||
            source.status === 'Cancelled' ||
            source.status === MarketingSourceStatus.Error ||
            source.status === MarketingSourceStatus.Warning
    )

    if (sourcesWithIssues.length === 0 && !sourceValidationError) {
        return null
    }

    const hasErrors = sourcesWithIssues.some(
        ({ status }) => status === ExternalDataSchemaStatus.Failed || status === MarketingSourceStatus.Error
    )
    const hasWarnings =
        sourceValidationError ||
        sourcesWithIssues.some(
            ({ status }) => status === MarketingSourceStatus.Warning || status === ExternalDataSchemaStatus.Cancelled
        )
    const bannerType = hasErrors ? 'error' : hasWarnings ? 'warning' : 'info'

    return (
        <LemonBanner type={bannerType} className="mb-2 mt-4">
            <div className="space-y-2 min-w-0 break-words">
                {sourceValidationError && (
                    <div>Could not check source configuration. Reload the dashboard to try again.</div>
                )}
                {sourcesWithIssues.map((source) => (
                    <div key={source.id}>
                        <Link
                            to={
                                source.type === 'native'
                                    ? urls.dataWarehouseSource(`managed-${source.id}`)
                                    : urls.settings('environment-marketing-analytics')
                            }
                            data-attr="marketing-source-status-settings"
                        >
                            {source.type === 'native' ? nativeSourceDisplayLabel(source.source_type) : source.name}
                            {source.prefix ? ` (${source.prefix})` : ''}
                        </Link>
                        <span>{`: ${source.statusMessage}`}</span>
                    </div>
                ))}
            </div>
        </LemonBanner>
    )
}
