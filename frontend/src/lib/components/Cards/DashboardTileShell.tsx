import clsx from 'clsx'
import React from 'react'

import { Card } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export type DashboardTileShellProps = React.HTMLAttributes<HTMLDivElement> & {
    transparent?: boolean
    showResizeHandles?: boolean
}

export const DashboardTileShell = React.forwardRef<HTMLDivElement, DashboardTileShellProps>(function DashboardTileShell(
    { transparent, showResizeHandles, className, children, ...divProps },
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
            className={clsx(
                'rounded',
                !transparent && 'bg-surface-primary border',
                transparent && showResizeHandles && 'border border-dashed border-border',
                className
            )}
            {...divProps}
        >
            {children}
        </div>
    )
})
