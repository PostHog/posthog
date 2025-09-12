import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { ConversionGoalWarning, ProductTab } from './common'

export const WebAnalyticsHealthCheck = (): JSX.Element | null => {
    const { statusCheck, conversionGoalWarning, productTab } = useValues(webAnalyticsLogic)

    if (productTab === ProductTab.MARKETING) {
        return null
    }

    if (conversionGoalWarning) {
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

    if (!statusCheck.hasAuthorizedUrls) {
        return (
            <LemonBanner type="warning" className="mt-2">
                <p>
                    We couldn't find any authorized domains. Some of our Web analytics filters won't work correctly
                    until you let us know what domains you are sending your events from.
                </p>
                <p>
                    Please take some time to outline them for us in{' '}
                    <Link to={urls.settings('environment', 'web-analytics-authorized-urls')}>the settings</Link>.
                </p>
            </LemonBanner>
        )
    }

    if (productTab === ProductTab.WEB_VITALS) {
        if (!statusCheck.isSendingWebVitals) {
            return (
                <LemonBanner type="warning" className="mt-2">
                    <p>
                        No <code>$web_vitals</code> events have been received. Web Vitals won't work correctly (it'll be
                        a little empty!)
                    </p>
                    <p>
                        Please see{' '}
                        <Link to="https://posthog.com/docs/web-analytics/web-vitals">
                            documentation for how to set up web vitals
                        </Link>
                        .
                    </p>
                </LemonBanner>
            )
        }
    } else {
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
                        <Link to="https://posthog.com/docs/libraries/js">
                            documentation for how to set up posthog-js
                        </Link>
                        .
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
                        <Link to="https://posthog.com/docs/libraries/js">
                            documentation for how to set up posthog-js
                        </Link>
                        .
                    </p>
                </LemonBanner>
            )
        }
    }

    return null
}
