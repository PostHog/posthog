import { Skeleton } from '@posthog/quill'

import { BetsFieldSkeleton } from './BetsFieldSkeleton'

export function BetEditSkeleton(): JSX.Element {
    return (
        <div
            className="Bets__skeleton pointer-events-none flex max-w-170 flex-col gap-6 pt-7 select-none"
            role="status"
            aria-label="Loading bet"
        >
            <BetsFieldSkeleton />
            <BetsFieldSkeleton control="h-28" />
            <BetsFieldSkeleton />
            <Skeleton className="Bets__skeletonArea Bets__skeletonFade h-80" />
        </div>
    )
}
