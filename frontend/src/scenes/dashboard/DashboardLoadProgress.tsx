import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

export interface DashboardLoadProgressProps {
    completed: number
    total: number
}

/** Tiles are fetched a few at a time, so a tile still waiting for a slot draws the same spinner as a running one. */
export function DashboardLoadProgress({ completed, total }: DashboardLoadProgressProps): JSX.Element | null {
    if (total < 2) {
        return null
    }

    return (
        <div
            className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-2 text-sm text-secondary"
            data-attr="dashboard-load-progress"
        >
            {/* LemonProgress spans its container, so the width belongs to the wrapper. */}
            <div className="w-24 shrink-0">
                <LemonProgress percent={(completed / total) * 100} bgColor="var(--color-border-primary)" />
            </div>
            <span className="whitespace-nowrap">
                Loaded {completed} of {total} tiles
            </span>
            <span className="text-muted">Tiles load a few at a time.</span>
        </div>
    )
}
