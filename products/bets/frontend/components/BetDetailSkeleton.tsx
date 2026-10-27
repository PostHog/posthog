import { Skeleton } from '@posthog/quill'

import { BetIdeasSkeleton } from './BetIdeasSkeleton'
import { BetsListSkeleton } from './BetsListSkeleton'
import { BetsSkeletonLine } from './BetsSkeletonLine'

export function BetDetailSkeleton(): JSX.Element {
    return (
        <div
            className="Bets__skeletonDetail Bets__skeleton pointer-events-none select-none"
            role="status"
            aria-label="Loading bet"
        >
            <div className="Bets__skeletonIntro" aria-hidden>
                <div className="Bets__thesis mx-0 mt-0 mb-4 max-w-180 text-pretty">
                    <BetsSkeletonLine width="w-full" />
                    <BetsSkeletonLine width="w-1/2" />
                </div>
                <BetsSkeletonLine className="text-sm" width="w-56" />
            </div>
            <div className="Bets__skeletonMain min-w-0" aria-hidden>
                <Skeleton className="h-2.5 w-24 rounded-full" />
                <Skeleton className="mt-4 h-8 w-20 rounded-lg" />
                <Skeleton className="Bets__skeletonArea mt-10 h-40" />
                <BetIdeasSkeleton />
                <BetsListSkeleton className="mt-12" widths={['w-3/5', 'w-2/5', 'w-1/2']} />
            </div>
            <div className="Bets__skeletonRail flex min-w-0 flex-col gap-5" aria-hidden>
                <Skeleton className="Bets__skeletonArea h-28" />
                <Skeleton className="Bets__skeletonArea h-14" />
                <Skeleton className="Bets__skeletonArea Bets__skeletonFade h-72" />
            </div>
        </div>
    )
}
