import { Tooltip } from '@posthog/lemon-ui'
import { ReactNode } from 'react'

interface OverviewItemBase {
    icon?: ReactNode
    label: string
    tooltipTitle?: string
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
            <div className="grid grid-cols-1 place-items-center gap-4 p-2 @xs/og:grid-cols-2 @md/og:grid-cols-3 ">
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
}: {
    children?: ReactNode
    description: ReactNode
    label: ReactNode
    icon?: ReactNode
}): JSX.Element {
    return (
        <Tooltip title={description}>
            <div className="flex flex-1 w-full justify-between items-center ">
                <div className="text-sm">
                    {icon} {label}
                </div>
                <div>{children}</div>
            </div>
        </Tooltip>
    )
}
