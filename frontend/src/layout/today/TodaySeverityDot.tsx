import { Dot } from '@posthog/quill'

import { SEVERITY_INDICATOR, TodayRailSeverity } from './todayRailSeverity'

export function TodaySeverityDot({
    severity,
    className,
}: {
    severity: TodayRailSeverity
    className?: string
}): JSX.Element | null {
    const indicator = SEVERITY_INDICATOR[severity]
    return indicator ? <Dot variant={indicator} aria-hidden data-slot="severity-dot" className={className} /> : null
}
