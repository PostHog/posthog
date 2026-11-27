import { Skeleton } from '@posthog/quill'

const ROWS = 4
const COLUMNS = 12

export function HeatmapLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-0.5 pl-10" aria-busy="true">
            {Array.from({ length: ROWS }, (_, row) => (
                <div key={row} className="flex min-h-0 flex-1 gap-0.5">
                    {Array.from({ length: COLUMNS }, (_, column) => (
                        <Skeleton key={column} className="h-full flex-1 rounded-none" />
                    ))}
                </div>
            ))}
        </div>
    )
}
