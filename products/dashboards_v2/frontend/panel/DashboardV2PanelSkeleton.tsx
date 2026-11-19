import { Skeleton } from '@posthog/quill'

const ROW_WIDTHS = ['w-4/5', 'w-3/5', 'w-11/12', 'w-2/3', 'w-3/4', 'w-1/2', 'w-5/6', 'w-3/5']
const BAR_HEIGHTS = [
    'h-2/5',
    'h-3/5',
    'h-1/2',
    'h-4/5',
    'h-2/3',
    'h-1/3',
    'h-3/4',
    'h-1/2',
    'h-3/5',
    'h-5/6',
    'h-2/5',
    'h-2/3',
]

export function DashboardV2PanelSkeleton({ type }: { type: string }): JSX.Element {
    if (type === 'table' || type === 'logs' || type === 'traces') {
        return (
            <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden" data-attr="dashboard-v2-panel-skeleton">
                {ROW_WIDTHS.map((width, index) => (
                    <Skeleton key={index} className={`h-3 shrink-0 ${width}`} />
                ))}
            </div>
        )
    }
    if (type === 'stat' || type === 'gauge') {
        return (
            <div className="flex h-full min-h-0 items-center justify-center" data-attr="dashboard-v2-panel-skeleton">
                <Skeleton className="h-10 w-24" />
            </div>
        )
    }
    return (
        <div className="flex h-full min-h-0 items-end gap-1 overflow-hidden" data-attr="dashboard-v2-panel-skeleton">
            {BAR_HEIGHTS.map((height, index) => (
                <Skeleton key={index} className={`flex-1 ${height}`} />
            ))}
        </div>
    )
}
