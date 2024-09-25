import { Tooltip } from '@posthog/lemon-ui'

export function OverviewGrid({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="grid grid-cols-3 place-items-center">{children}</div>
}

export function OverviewGridItem({
    children,
    description,
    label,
}: {
    children: React.ReactNode
    description: string
    label: string
}): JSX.Element {
    return (
        <Tooltip title={description}>
            <div className="flex-1 p-2 text-center">
                <div className="text-sm">{label}</div>
                <div className="text-lg font-semibold">{children}</div>
            </div>
        </Tooltip>
    )
}
