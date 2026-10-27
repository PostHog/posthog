import { BetsListSkeleton } from './BetsListSkeleton'

export function BetActivitySkeleton(): JSX.Element {
    return (
        <div className="Bets__skeleton pointer-events-none select-none" aria-hidden>
            <BetsListSkeleton className="Bets__skeletonFade" widths={['w-3/5', 'w-4/5', 'w-1/2', 'w-2/3']} />
        </div>
    )
}
