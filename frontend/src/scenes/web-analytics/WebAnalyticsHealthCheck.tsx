import { useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

export const WebAnalyticsHealthCheck = (): JSX.Element | null => {
    const { statusCheck } = useValues(webAnalyticsLogic)

    // No need to show loading or error states for this warning
    if (!statusCheck) {
        return null
    }

    if (statusCheck.shouldWarnAboutNoPageviews) {
        return (
            <LemonBanner type={'warning'} className={'mt-2'}>
                <p>
                    No <code>$pageview</code>{' '}
                    {statusCheck.shouldWarnAboutNoPageleaves ? (
                        <>
                            or <code>$pageleave</code>{' '}
                        </>
                    ) : null}
                    events have been received, please read{' '}
                    <Link to={'https://posthog.com/docs/product-analytics/capture-events'}>the documentation</Link> and
                    fix this before using Web Analytics.
                </p>
            </LemonBanner>
        )
    } else if (statusCheck.shouldWarnAboutNoPageleaves) {
        return (
            <LemonBanner type={'warning'} className={'mt-2'}>
                <p>
                    No <code>$pageleave</code> events have been received, this means that Bounce rate and Session
                    Duration might be inaccurate. Please read{' '}
                    <Link to={'https://posthog.com/docs/product-analytics/capture-events'}>the documentation</Link> and
                    fix this before using Web Analytics.
                </p>
            </LemonBanner>
        )
    }
    return null
}
