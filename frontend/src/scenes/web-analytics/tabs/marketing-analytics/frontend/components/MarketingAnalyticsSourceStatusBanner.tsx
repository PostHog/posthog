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

    return (
        <LemonBanner
            type={syncingOrFailedSources.some((s) => s.status === 'Failed') ? 'error' : 'info'}
            className="mb-2 mt-4"
        >
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
                    {syncingOrFailedSources.filter((s) => s.status === 'Running').length > 0 && (
                        <>
                            <strong>
                                {syncingOrFailedSources.filter((s) => s.status === 'Running').length} source
                                {syncingOrFailedSources.filter((s) => s.status === 'Running').length > 1
                                    ? 's are'
                                    : ' is'}{' '}
                                syncing
                            </strong>
                            .{' '}
                        </>
                    )}
                    {syncingOrFailedSources.filter((s) => s.status === 'Failed').length > 0 && (
                        <>
                            <strong>
                                {syncingOrFailedSources.filter((s) => s.status === 'Failed').length} source
                                {syncingOrFailedSources.filter((s) => s.status === 'Failed').length > 1
                                    ? 's have'
                                    : ' has'}{' '}
                                failed while syncing
                            </strong>
                            .{' '}
                        </>
                    )}
                    {syncingOrFailedSources.filter((s) => s.status === 'Paused').length > 0 && (
                        <>
                            <strong>
                                {syncingOrFailedSources.filter((s) => s.status === 'Paused').length} source
                                {syncingOrFailedSources.filter((s) => s.status === 'Paused').length > 1
                                    ? 's are'
                                    : ' is'}{' '}
                                paused
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
