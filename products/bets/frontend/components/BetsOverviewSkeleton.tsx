import { Skeleton } from '@posthog/quill'

import { BetsListSkeleton } from './BetsListSkeleton'

export function BetsOverviewSkeleton(): JSX.Element {
    return (
        <div className="Bets__skeleton pointer-events-none select-none" role="status" aria-label="Loading bets">
            <div className="Bets__summary mb-6 py-8" aria-hidden>
                <div className="flex flex-col gap-4 pt-1">
                    <Skeleton className="h-2.5 w-20 rounded-full" />
                    <Skeleton className="h-8 w-40 rounded-lg" />
                </div>
                <div className="flex items-start justify-between gap-6">
                    <div className="flex flex-col gap-4 pt-1">
                        <Skeleton className="h-2.5 w-28 rounded-full" />
                        <Skeleton className="h-8 w-20 rounded-lg" />
                    </div>
                    <Skeleton className="Bets__skeletonArea h-[90px] w-40 shrink-0" />
                </div>
            </div>
            <div className="mt-8" aria-hidden>
                <Skeleton className="h-3 w-40 rounded-full" />
                <BetsListSkeleton className="mt-8" widths={['w-1/3', 'w-1/2']} />
            </div>
        </div>
    )
}
