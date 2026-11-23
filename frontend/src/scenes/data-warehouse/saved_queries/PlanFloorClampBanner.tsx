import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

const CADENCE_UNITS: [seconds: number, singular: string][] = [
    [86400, 'day'],
    [3600, 'hour'],
    [60, 'minute'],
]

function everyCadence(seconds: number): string {
    const [unitSeconds, unit] = CADENCE_UNITS.find(([unitSeconds]) => seconds % unitSeconds === 0) ?? [1, 'second']
    const count = seconds / unitSeconds
    return count === 1 ? `every ${unit}` : `every ${count} ${unit}s`
}

export function planFloorClampMessage(
    subject: 'view' | 'endpoint',
    previousSeconds: number | null,
    planFloorSeconds: number
): string {
    const limited = `Your plan's refresh limit set this ${subject} to refresh ${everyCadence(planFloorSeconds)}.`
    return previousSeconds === null ? limited : `${limited} It refreshed ${everyCadence(previousSeconds)} before.`
}

export interface PlanFloorClampBannerProps {
    subject: 'view' | 'endpoint'
    subjectId: string
    previousSeconds: number | null
    planFloorSeconds: number
    at: string
    className?: string
}

export function PlanFloorClampBanner({
    subject,
    subjectId,
    previousSeconds,
    planFloorSeconds,
    at,
    className,
}: PlanFloorClampBannerProps): JSX.Element {
    return (
        <LemonBanner
            type="info"
            className={className}
            dismissKey={`plan-floor-clamp-${subjectId}-${at}`}
            action={{
                children: 'Upgrade plan',
                to: urls.organizationBilling(),
                'data-attr': 'plan-floor-clamp-upgrade',
            }}
        >
            {planFloorClampMessage(subject, previousSeconds, planFloorSeconds)}
        </LemonBanner>
    )
}
