import clsx from 'clsx'
import { ReactNode } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

interface OverviewItemBase {
    icon?: ReactNode
    label: string
    valueTooltip?: ReactNode
    keyTooltip?: ReactNode
}

type TextOverviewItem = OverviewItemBase & {
    type: 'text'
    value: ReactNode
}

type PropertyOverviewItem = OverviewItemBase & {
    type: 'property'
    property: string
    value?: string | undefined
}

export type OverviewItem = TextOverviewItem | PropertyOverviewItem

export function OverviewGrid({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="@container/og">
            <div className="grid grid-cols-1 place-items-center gap-4 px-2 py-1 @md/og:grid-cols-2 @2xl/og:grid-cols-3">
                {children}
            </div>
        </div>
    )
}

export function OverviewGridItem({
    children,
    description,
    label,
    icon,
    fadeLabel,
    itemKeyTooltip,
}: {
    children?: ReactNode
    description: ReactNode
    label: ReactNode
    icon?: ReactNode
    fadeLabel?: boolean
    itemKeyTooltip?: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-1 w-full justify-between items-center deprecated-space-x-4">
            <div className={clsx('text-sm', fadeLabel && 'font-light')}>
                <Tooltip title={itemKeyTooltip}>
                    {icon} {label}
                </Tooltip>
            </div>
            <Tooltip title={description}>
                <div className="overflow-x-auto">{children}</div>
            </Tooltip>
        </div>
    )
}
