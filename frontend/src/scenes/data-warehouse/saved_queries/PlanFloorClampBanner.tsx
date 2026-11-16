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
    const now = `This ${subject} now refreshes ${everyCadence(planFloorSeconds)}, the fastest your plan allows.`
    return previousSeconds === null ? now : `${now} It refreshed ${everyCadence(previousSeconds)} before.`
}

export interface PlanFloorClampBannerProps {
    subject: 'view' | 'endpoint'
    subjectId: string
    previousSeconds: number | null
    planFloorSeconds: number
    at: string
}

export function PlanFloorClampBanner({
    subject,
    subjectId,
    previousSeconds,
    planFloorSeconds,
    at,
}: PlanFloorClampBannerProps): JSX.Element {
    return (
        <LemonBanner
            type="info"
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
