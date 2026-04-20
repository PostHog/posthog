import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import { ExternalDataSchemaStatus } from '~/types'

import { MarketingSourceStatus, marketingAnalyticsLogic } from '../logic/marketingAnalyticsLogic'

type StatusCount = Record<
    | ExternalDataSchemaStatus.Running
    | ExternalDataSchemaStatus.Failed
    | ExternalDataSchemaStatus.Paused
    | MarketingSourceStatus.Warning,
    number
>

const getStatusCounts = (sources: { status: string }[]): StatusCount => {
    const counts: StatusCount = {
        [ExternalDataSchemaStatus.Running]: 0,
        [ExternalDataSchemaStatus.Failed]: 0,
        [ExternalDataSchemaStatus.Paused]: 0,
        [MarketingSourceStatus.Warning]: 0,
    }

    for (const source of sources) {
        if (source.status === ExternalDataSchemaStatus.Running) {
            counts[ExternalDataSchemaStatus.Running] += 1
        } else if (source.status === ExternalDataSchemaStatus.Failed) {
            counts[ExternalDataSchemaStatus.Failed] += 1
        } else if (source.status === ExternalDataSchemaStatus.Paused) {
            counts[ExternalDataSchemaStatus.Paused] += 1
        } else if (source.status === MarketingSourceStatus.Warning) {
            counts[MarketingSourceStatus.Warning] += 1
        }
    }

    return counts
}

const SourceStatusMessage = ({
    length,
    singularVerb,
    pluralVerb,
    message,
}: {
    length: number
    singularVerb: string
    pluralVerb: string
    message: string
}): JSX.Element | null => {
    if (length === 0) {
        return null
    }
    return (
        <>
            <strong>
                {length} source{length > 1 ? 's' : ''} {length > 1 ? pluralVerb : singularVerb} {message}
            </strong>
            .{' '}
        </>
    )
}

export const MarketingAnalyticsSourceStatusBanner = (): JSX.Element | null => {
    const { allAvailableSourcesWithStatus } = useValues(marketingAnalyticsLogic)

    const sourcesWithIssues = allAvailableSourcesWithStatus.filter(
        (source) =>
            source.status === 'Running' ||
            source.status === 'Failed' ||
            source.status === 'Paused' ||
            source.status === MarketingSourceStatus.Warning
    )

    if (sourcesWithIssues.length === 0) {
        return null
    }

    const statusCounts = getStatusCounts(sourcesWithIssues)
    const hasErrors = statusCounts[ExternalDataSchemaStatus.Failed] > 0
    const hasWarnings = statusCounts[MarketingSourceStatus.Warning] > 0
    const bannerType = hasErrors ? 'error' : hasWarnings ? 'warning' : 'info'

    return (
        <LemonBanner type={bannerType} className="mb-2 mt-4">
            {sourcesWithIssues.length === 1 ? (
                <>
                    <strong>{sourcesWithIssues[0].name}</strong>
                    {sourcesWithIssues[0].status === MarketingSourceStatus.Warning
                        ? `: ${sourcesWithIssues[0].statusMessage}`
                        : ` is currently ${
                              sourcesWithIssues[0].status === 'Running'
                                  ? 'syncing'
                                  : sourcesWithIssues[0].status === 'Failed'
                                    ? 'failed'
                                    : 'paused'
                          }. ${sourcesWithIssues[0].statusMessage}`}
                </>
            ) : (
                <>
                    <SourceStatusMessage
                        length={statusCounts[MarketingSourceStatus.Warning]}
                        singularVerb="has"
                        pluralVerb="have"
                        message="missing required tables for import"
                    />
                    <SourceStatusMessage
                        length={statusCounts[ExternalDataSchemaStatus.Running]}
                        singularVerb="is"
                        pluralVerb="are"
                        message="syncing"
                    />
                    <SourceStatusMessage
                        length={statusCounts[ExternalDataSchemaStatus.Failed]}
                        singularVerb="has"
                        pluralVerb="have"
                        message="failed while syncing"
                    />
                    <SourceStatusMessage
                        length={statusCounts[ExternalDataSchemaStatus.Paused]}
                        singularVerb="is"
                        pluralVerb="are"
                        message="paused"
                    />
                </>
            )}{' '}
            Check{' '}
            <Link to={urls.settings('environment-marketing-analytics')} target="_blank">
                marketing analytics settings
            </Link>{' '}
            for more details.
        </LemonBanner>
    )
}
