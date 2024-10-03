import { Tooltip } from '@posthog/lemon-ui'

export function OverviewGrid({ children }: { children: React.ReactNode }): JSX.Element {
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
}: {
    children: React.ReactNode
    description: React.ReactNode
    label: React.ReactNode
}): JSX.Element {
    return (
        <Tooltip title={description}>
            <div className="flex flex-1 w-full justify-between items-center ">
                <div className="text-sm">{label}</div>
                <div className="text-lg font-semibold">{children}</div>
            </div>
        </Tooltip>
    )
}
