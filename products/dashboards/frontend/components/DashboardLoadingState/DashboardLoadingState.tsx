import { LemonSkeleton } from '@posthog/lemon-ui'

export function DashboardLoadingState({
    showControls = true,
    tileCount = 8,
}: { showControls?: boolean; tileCount?: number } = {}): JSX.Element {
    return (
        <div className="flex flex-col gap-4" aria-label="Loading dashboard">
            {showControls && (
                <div
                    className="flex flex-wrap items-center justify-between gap-2"
                    data-attr="dashboard-loading-controls"
                >
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSkeleton className="h-8 w-36 rounded" />
                        <LemonSkeleton className="h-8 w-24 rounded" />
                        <LemonSkeleton className="h-8 w-20 rounded" />
                        <LemonSkeleton className="h-8 w-28 rounded" />
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonSkeleton className="h-4 w-32" />
                        <LemonSkeleton className="h-8 w-24 rounded" />
                    </div>
                </div>
            )}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {Array.from({ length: tileCount }, (_, index) => (
                    <div
                        key={index}
                        className="border rounded bg-surface-primary p-4 min-h-96"
                        data-attr="dashboard-loading-tile"
                    >
                        <div className="flex items-center justify-between gap-4 mb-6">
                            <LemonSkeleton className="h-4 w-2/5" />
                            <LemonSkeleton className="h-8 w-8 rounded" />
                        </div>
                        <LemonSkeleton className="h-40 w-full rounded" />
                    </div>
                ))}
            </div>
        </div>
    )
}
