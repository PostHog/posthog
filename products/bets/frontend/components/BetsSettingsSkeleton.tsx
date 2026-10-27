import { Skeleton } from '@posthog/quill'

import { BetsFieldSkeleton } from './BetsFieldSkeleton'

export function BetsSettingsSkeleton(): JSX.Element {
    return (
        <div
            className="Bets__skeleton pointer-events-none flex max-w-170 flex-col gap-6 pt-7 select-none"
            role="status"
            aria-label="Loading settings"
        >
            <BetsFieldSkeleton />
            <BetsFieldSkeleton />
            <div className="flex flex-col gap-4">
                <Skeleton className="h-3 w-20 rounded-full" />
                <Skeleton className="Bets__skeletonArea Bets__skeletonFade h-64" />
            </div>
        </div>
    )
}
