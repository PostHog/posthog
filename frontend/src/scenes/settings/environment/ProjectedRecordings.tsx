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

    const rate = typeof sampleRatePercent === 'number' ? sampleRatePercent : 100
    const projected = projectedWeeklyRecordings(weeklySessions, rate)

    return (
        <p className="text-xs text-muted mb-0">
            About <strong>{humanFriendlyNumber(projected)}</strong> recordings per week at {rate}%, based on{' '}
            {humanFriendlyNumber(weeklySessions)} sessions in the last 7 days. Triggers and the duration threshold can
            lower this.
        </p>
    )
}
