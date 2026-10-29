import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { FLAG_EVALUATIONS_RETENTION_DAYS, FlagCallsRetentionGap } from 'scenes/feature-flags/flagEvaluationsTable'

export function FlagCallsRetentionNotice({
    gap,
    retentionStartDate,
}: {
    gap: FlagCallsRetentionGap
    retentionStartDate: string
}): JSX.Element {
    const date = <span translate="no">{dayjs.utc(retentionStartDate).format('MMMM D, YYYY')}</span>
    return (
        <LemonBanner type="info" className="m-2">
            This insight includes feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days only.{' '}
            {gap === 'periods' ? (
                <>Periods before {date} show no calls.</>
            ) : (
                <>The first period depends on calls from before {date}, so its results may be inaccurate.</>
            )}
        </LemonBanner>
    )
}
