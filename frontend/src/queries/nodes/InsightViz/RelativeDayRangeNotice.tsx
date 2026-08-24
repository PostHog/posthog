import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { InsightQueryNode } from '~/queries/schema/schema-general'

const RELATIVE_DAY_RANGE_REGEX = /^-\d+d$/

/** Whether corrected relative-day semantics can produce different results for this query.
 * Mirrors relative day ranges handled by relative_date_parse in posthog/utils.py. */
export function isAffectedByRelativeDayRangeChange(source: InsightQueryNode | null | undefined): boolean {
    if (!source || !('dateRange' in source)) {
        return false
    }

    const dateRange = source.dateRange
    return (
        !!dateRange && !dateRange.date_to && !!dateRange.date_from && RELATIVE_DAY_RANGE_REGEX.test(dateRange.date_from)
    )
}

// Remove after 2026-11-24, once affected users have had a full quarter to see it.
export function RelativeDayRangeNotice({
    source,
    className,
}: {
    source: InsightQueryNode | null | undefined
    className?: string
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (
        featureFlags[FEATURE_FLAGS.RELATIVE_DAY_RANGE_NOTICE] === false ||
        !isAffectedByRelativeDayRangeChange(source)
    ) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey="relative-day-range-notice" className={className}>
            Relative day ranges previously included one more calendar day than their label indicated. They now include
            the stated number of days, including today. Results and comparisons may differ.
        </LemonBanner>
    )
}
