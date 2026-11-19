import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { DashboardControl, dashboardControlScopeText, isDashboardControlHidden } from './dashboardControls'

/** Wraps one filter control: hides it when it changes no insight, and says in a tooltip how many insights it changes. */
export function DashboardControlSlot({
    control,
    hasValue,
    className,
    children,
}: {
    control: DashboardControl
    hasValue: boolean
    className?: string
    children: ReactNode
}): JSX.Element | null {
    const { dashboardControlScopes } = useValues(dashboardLogic)
    const controlsEnabled = useFeatureFlag('METRICS_DASHBOARD_CONTROLS')

    if (!controlsEnabled) {
        return <div className={className}>{children}</div>
    }
    const scope = dashboardControlScopes[control]
    if (isDashboardControlHidden(scope, hasValue)) {
        return null
    }
    const scopeText = dashboardControlScopeText(scope)
    return (
        <Tooltip title={scopeText} placement="top" delayMs={300}>
            <div className={className}>{children}</div>
        </Tooltip>
    )
}
