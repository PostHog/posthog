import clsx from 'clsx'
import React from 'react'

import { Card } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export type DashboardTileShellProps = React.HTMLAttributes<HTMLDivElement> & {
    transparent?: boolean | null
}

export const DashboardTileShell = React.forwardRef<HTMLDivElement, DashboardTileShellProps>(function DashboardTileShell(
    { transparent, className, children, ...divProps },
    ref
): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav && !transparent) {
        return (
            <Card flush ref={ref} className={clsx('overflow-visible pt-0', className)} {...divProps}>
                {children}
            </Card>
        )
    }

    return (
        <div
            ref={ref}
            className={clsx('rounded', !transparent && 'bg-surface-primary border', className)}
            {...divProps}
        >
            {children}
        </div>
    )
})
