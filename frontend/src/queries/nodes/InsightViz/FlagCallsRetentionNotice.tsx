import { LemonBanner } from '@posthog/lemon-ui'

import {
    FLAG_EVALUATIONS_RETENTION_DAYS,
    flagEvaluationsRetentionStart,
} from 'scenes/feature-flags/flagEvaluationsRetention'

export function FlagCallsRetentionNotice(): JSX.Element {
    return (
        <LemonBanner type="info" className="m-2">
            This insight includes feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days only. Periods
            before {flagEvaluationsRetentionStart().format('MMMM D, YYYY')} show no calls.
        </LemonBanner>
    )
}
