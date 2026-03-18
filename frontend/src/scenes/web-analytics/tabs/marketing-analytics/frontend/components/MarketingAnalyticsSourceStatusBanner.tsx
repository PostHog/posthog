import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import { ExternalDataSchemaStatus } from '~/types'

import { marketingAnalyticsLogic } from '../logic/marketingAnalyticsLogic'

type StatusCount = Record<
    ExternalDataSchemaStatus.Running | ExternalDataSchemaStatus.Failed | ExternalDataSchemaStatus.Paused,
    number
>

const getStatusCounts = (sources: { status: string }[]): StatusCount => {
    const counts: StatusCount = {
        [ExternalDataSchemaStatus.Running]: 0,
        [ExternalDataSchemaStatus.Failed]: 0,
        [ExternalDataSchemaStatus.Paused]: 0,
    }

    for (const source of sources) {
        if (source.status === ExternalDataSchemaStatus.Running) {
            counts[ExternalDataSchemaStatus.Running] += 1
        } else if (source.status === ExternalDataSchemaStatus.Failed) {
            counts[ExternalDataSchemaStatus.Failed] += 1
        } else if (source.status === ExternalDataSchemaStatus.Paused) {
            counts[ExternalDataSchemaStatus.Paused] += 1
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

    const syncingOrFailedSources = allAvailableSourcesWithStatus.filter(
        (source) => source.status === 'Running' || source.status === 'Failed' || source.status === 'Paused'
    )

    if (syncingOrFailedSources.length === 0) {
        return null
    }

    const statusCounts = getStatusCounts(syncingOrFailedSources)

    return (
        <LemonBanner type={statusCounts[ExternalDataSchemaStatus.Failed] > 0 ? 'error' : 'info'} className="mb-2 mt-4">
            {syncingOrFailedSources.length === 1 ? (
                <>
                    <strong>{syncingOrFailedSources[0].name}</strong> is currently{' '}
                    {syncingOrFailedSources[0].status === 'Running'
                        ? 'syncing'
                        : syncingOrFailedSources[0].status === 'Failed'
                          ? 'failed'
                          : 'paused'}
                    . {syncingOrFailedSources[0].statusMessage}
                </>
            ) : (
                <>
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
