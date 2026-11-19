import { IconInfo } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'
import { Callout, CalloutContent, CalloutDescription, CalloutIcon } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { dayjs } from 'lib/dayjs'
import { DATE_FORMAT } from 'lib/utils/datetime'
import { FLAG_EVALUATIONS_RETENTION_DAYS, FlagCallsRetentionGap } from 'scenes/feature-flags/flagEvaluationsTable'

export function FlagCallsRetentionNotice({
    gap,
    retentionStartDate,
}: {
    gap: FlagCallsRetentionGap
    retentionStartDate: string
}): JSX.Element {
    const quillSurface = useQuillSurface()

    const date = <span translate="no">{dayjs.utc(retentionStartDate).format(DATE_FORMAT)}</span>
    const message = (
        <>
            This insight includes feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days only.{' '}
            {gap === 'periods' ? (
                <>Periods before {date} show no calls.</>
            ) : (
                <>The first period depends on calls from before {date}, so its results may be inaccurate.</>
            )}
        </>
    )

    if (quillSurface) {
        return (
            <Callout tone="info" className="m-2 w-auto">
                <CalloutIcon>
                    <IconInfo />
                </CalloutIcon>
                <CalloutContent>
                    <CalloutDescription className="text-xs">{message}</CalloutDescription>
                </CalloutContent>
            </Callout>
        )
    }

    return (
        <LemonBanner type="info" className="m-2">
            {message}
        </LemonBanner>
    )
}
