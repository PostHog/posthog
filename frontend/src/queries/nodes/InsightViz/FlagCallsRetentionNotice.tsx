import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import {
    FLAG_EVALUATIONS_RETENTION_DAYS,
    FlagCallsInsightResponse,
    insightFlagEvaluationsRetentionStartDate,
} from 'scenes/feature-flags/flagEvaluationsTable'

export function FlagCallsRetentionNotice({
    insightData,
}: {
    insightData: FlagCallsInsightResponse | null
}): JSX.Element {
    return (
        <LemonBanner type="info" className="m-2">
            This insight includes feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days only. Periods
            before {dayjs.utc(insightFlagEvaluationsRetentionStartDate(insightData)).format('MMMM D, YYYY')} show no
            calls.
        </LemonBanner>
    )
}
