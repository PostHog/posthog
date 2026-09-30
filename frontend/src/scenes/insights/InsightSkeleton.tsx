import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { InsightVisualizationSkeleton } from '~/lib/components/Cards/InsightCard/InsightVisualizationSkeleton'

export function InsightSkeleton(): JSX.Element {
    return (
        <div className="scene-content flex flex-col gap-y-4 relative z-10" aria-busy="true">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                    <LemonSkeleton className="size-8 shrink-0" />
                    <LemonSkeleton className="h-6 w-64 max-w-full" />
                </div>

                <div className="flex flex-wrap gap-2">
                    <LemonSkeleton className="h-8 w-32" />
                    <LemonSkeleton className="h-8 w-24" />
                    <LemonSkeleton className="h-8 w-14" />
                </div>
            </div>

            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-4 w-3/4 max-w-full" />
                <LemonSkeleton className="h-4 w-1/2 max-w-full" />
                <LemonSkeleton className="h-3 w-64 max-w-full" />
            </div>

            <div className="rounded border bg-primary p-4">
                <div className="mb-4 flex flex-wrap justify-center gap-x-4 gap-y-2">
                    <LemonSkeleton className="h-3 w-28" />
                    <LemonSkeleton className="h-3 w-24" />
                    <LemonSkeleton className="h-3 w-28" />
                    <LemonSkeleton className="h-3 w-24" />
                </div>
                <div className="InsightVizDisplay min-h-[var(--insight-viz-min-height)]">
                    <InsightVisualizationSkeleton />
                </div>
            </div>
        </div>
    )
}
