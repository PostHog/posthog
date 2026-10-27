import { Skeleton } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

export function BetsSkeletonLine({ className, width }: { className?: string; width?: string }): JSX.Element {
    return (
        <div className={cn('flex h-lh min-w-0 items-center', className)}>
            {width && <Skeleton className={cn('Bets__skeletonInk', width)} />}
        </div>
    )
}
