import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { FLAG_EVALUATIONS_RETENTION_DAYS } from 'scenes/feature-flags/flagEvaluationsTable'

export function FlagCallsRetentionNotice({ retentionStartDate }: { retentionStartDate: string }): JSX.Element {
    return (
        <LemonBanner type="info" className="m-2">
            This insight includes feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days only. Periods
            before <span translate="no">{dayjs.utc(retentionStartDate).format('MMMM D, YYYY')}</span> show no calls.
        </LemonBanner>
    )
}
