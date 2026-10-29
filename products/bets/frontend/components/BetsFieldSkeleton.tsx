import { Skeleton } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

export function BetsFieldSkeleton({ control = 'h-8' }: { control?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 min-w-0">
            <Skeleton className="h-2.5 w-24 rounded-full" />
            <Skeleton className={cn('Bets__skeletonArea', control)} />
        </div>
    )
}
