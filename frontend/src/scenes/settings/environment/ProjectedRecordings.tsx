import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { sessionVolumeLogic } from './sessionVolumeLogic'

/** Recordings expected per week at a sample rate, from recent total session volume. */
export function projectedWeeklyRecordings(weeklySessions: number, sampleRatePercent: number): number {
    const rate = Math.min(Math.max(sampleRatePercent, 0), 100) / 100
    return Math.round(weeklySessions * rate)
}

export function ProjectedRecordings({
    sampleRatePercent,
}: {
    sampleRatePercent: number | null | undefined
}): JSX.Element | null {
    const { weeklySessions, weeklySessionsLoading } = useValues(sessionVolumeLogic)

    if (weeklySessionsLoading) {
        return (
            <p className="text-xs text-muted mb-0 flex items-center gap-1">
                <Spinner /> Estimating recordings per week
            </p>
        )
    }

    if (weeklySessions == null || weeklySessions === 0) {
        return null
    }

    // A number input reports NaN when cleared, and its DOM min/max do not clamp typed values. Skip any
    // rate that is missing, non-finite, or out of range so the estimate never reads "NaN" or shows a
    // count that disagrees with the printed rate.
    if (
        sampleRatePercent == null ||
        !Number.isFinite(sampleRatePercent) ||
        sampleRatePercent < 0 ||
        sampleRatePercent > 100
    ) {
        return null
    }

    const projected = projectedWeeklyRecordings(weeklySessions, sampleRatePercent)

    return (
        <p className="text-xs text-muted mb-0">
            About <strong>{humanFriendlyNumber(projected)}</strong> recordings per week at {sampleRatePercent}%, based
            on {humanFriendlyNumber(weeklySessions)} sessions in the last 7 days. Triggers and the duration threshold
            can lower this.
        </p>
    )
}
