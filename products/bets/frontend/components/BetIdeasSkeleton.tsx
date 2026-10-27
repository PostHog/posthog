import { Skeleton } from '@posthog/quill'

export function BetIdeasSkeleton(): JSX.Element {
    return (
        <div className="mt-10 flex flex-col gap-3" aria-hidden>
            <Skeleton className="h-2.5 w-16 rounded-full" />
            <Skeleton className="Bets__skeletonArea h-36" />
            <Skeleton className="Bets__skeletonArea Bets__skeletonFade h-36" />
        </div>
    )
}
