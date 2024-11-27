import { useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { ConversionGoalWarning, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

export const WebAnalyticsHealthCheck = (): JSX.Element | null => {
    const { statusCheck, conversionGoalWarning } = useValues(webAnalyticsLogic)
    const isFlagConversionGoalWarningsSet = useFeatureFlag('WEB_ANALYTICS_WARN_CUSTOM_EVENT_NO_SESSION')

    if (conversionGoalWarning && isFlagConversionGoalWarningsSet) {
        switch (conversionGoalWarning) {
            case ConversionGoalWarning.CustomEventWithNoSessionId:
                return (
                    <LemonBanner type="warning" className="mt-2">
                        <p>
                            A custom event has been set as a conversion goal, but it has been seen with no{' '}
                            <code>$session_id</code>. This means that some queries will not be able to include these
                            events.
                        </p>
                        <p>
                            To fix this, please see{' '}
                            <Link to="https://posthog.com/docs/data/sessions#custom-session-ids">
                                documentation for custom session IDs
                            </Link>
                            .
                        </p>
                    </LemonBanner>
                )
        }
    }

    // No need to show loading or error states for this warning
    if (!statusCheck) {
        return null
    }

    if (!statusCheck.isSendingPageViews) {
        return (
            <LemonBanner type="warning" className="mt-2">
                <p>
                    No <code>$pageview</code>{' '}
                    {!statusCheck.isSendingPageLeaves ? (
                        <>
                            or <code>$pageleave</code>{' '}
                        </>
                    ) : null}
                    events have been received. Web analytics won't work correctly (it'll be a little empty!)
                </p>
                <p>
                    Please see{' '}
                    <Link to="https://posthog.com/docs/libraries/js">documentation for how to set up posthog-js</Link>.
                </p>
            </LemonBanner>
        )
    } else if (!statusCheck.isSendingPageLeaves) {
        return (
            <LemonBanner type="warning" className="mt-2">
                <p>
                    No <code>$pageleave</code> events have been received, this means that Bounce rate and Session
                    duration might be inaccurate.
                </p>
                <p>
                    Please see{' '}
                    <Link to="https://posthog.com/docs/libraries/js">documentation for how to set up posthog-js</Link>.
                </p>
            </LemonBanner>
        )
    }
    return null
}
