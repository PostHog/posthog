import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { ConversionGoalWarning, ProductTab } from './common'

export const WebAnalyticsHealthCheck = (): JSX.Element | null => {
    const { conversionGoalWarning, productTab } = useValues(webAnalyticsLogic)

    if (productTab === ProductTab.MARKETING || productTab === ProductTab.HEALTH) {
        return null
    }

    if (conversionGoalWarning) {
        switch (conversionGoalWarning.warning) {
            case ConversionGoalWarning.CustomEventWithNoSessionId:
                return (
                    <LemonBanner type="warning" className="mt-2">
                        <p>
                            {conversionGoalWarning.sessionlessPercentage}% of{' '}
                            <code>{conversionGoalWarning.eventName}</code> events in this date range have no{' '}
                            <code>$session_id</code>, so they'll be missing from session-based queries for this
                            conversion goal.
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

    return null
}
