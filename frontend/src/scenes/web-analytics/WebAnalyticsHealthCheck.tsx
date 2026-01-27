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

    return null
}
