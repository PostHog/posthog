import { Skeleton } from '@posthog/quill'

export function BetsTableSkeleton(): JSX.Element {
    return (
        <div
            className="Bets__skeleton Bets__skeletonFade pointer-events-none select-none flex flex-col gap-3 pt-12"
            role="status"
            aria-label="Loading bets"
        >
            {[0, 1, 2].map((row) => (
                <Skeleton key={row} className="Bets__skeletonArea h-[60px]" />
            ))}
        </div>
    )
}
