import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

export interface DashboardLoadProgressProps {
    completed: number
    total: number
}

/**
 * Tiles are fetched a few at a time, so a tile that has no slot yet draws the same spinner as a
 * running one. The count beside the grid is the evidence that the dashboard is still filling in.
 */
export function DashboardLoadProgress({ completed, total }: DashboardLoadProgressProps): JSX.Element | null {
    if (total < 2) {
        return null
    }

    return (
        <div
            className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-2 text-sm text-secondary"
            data-attr="dashboard-load-progress"
        >
            <LemonProgress percent={(completed / total) * 100} className="w-24 shrink-0" />
            <span className="whitespace-nowrap">
                Loaded {completed} of {total} tiles
            </span>
            <span className="text-muted">Tiles load a few at a time.</span>
        </div>
    )
}
