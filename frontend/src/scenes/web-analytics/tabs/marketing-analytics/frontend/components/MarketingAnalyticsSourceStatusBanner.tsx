import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import { marketingAnalyticsLogic } from '../logic/marketingAnalyticsLogic'

export const MarketingAnalyticsSourceStatusBanner = (): JSX.Element | null => {
    const { allAvailableSourcesWithStatus } = useValues(marketingAnalyticsLogic)

    const syncingOrFailedSources = allAvailableSourcesWithStatus.filter(
        (source) => source.status === 'Running' || source.status === 'Failed' || source.status === 'Paused'
    )

    if (syncingOrFailedSources.length === 0) {
        return null
    }

    const runningSources = syncingOrFailedSources.filter((s) => s.status === 'Running')
    const failedSources = syncingOrFailedSources.filter((s) => s.status === 'Failed')
    const pausedSources = syncingOrFailedSources.filter((s) => s.status === 'Paused')

    return (
        <LemonBanner type={failedSources.length > 0 ? 'error' : 'info'} className="mb-2 mt-4">
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
                    {runningSources.length > 0 && (
                        <>
                            <strong>
                                {runningSources.length} source{runningSources.length > 1 ? 's are' : ' is'} syncing
                            </strong>
                            .{' '}
                        </>
                    )}
                    {failedSources.length > 0 && (
                        <>
                            <strong>
                                {failedSources.length} source{failedSources.length > 1 ? 's have' : ' has'} failed while
                                syncing
                            </strong>
                            .{' '}
                        </>
                    )}
                    {pausedSources.length > 0 && (
                        <>
                            <strong>
                                {pausedSources.length} source{pausedSources.length > 1 ? 's are' : ' is'} paused
                            </strong>
                            .{' '}
                        </>
                    )}
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
