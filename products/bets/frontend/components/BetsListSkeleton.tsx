import { Skeleton } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

export function BetsListSkeleton({ widths, className }: { widths: string[]; className?: string }): JSX.Element {
    return (
        <div className={cn('flex flex-col gap-5.5', className)}>
            {widths.map((width, index) => (
                <div key={index} className="flex items-center gap-3.5">
                    <Skeleton className="size-6 shrink-0 rounded-lg" />
                    <Skeleton className={cn('h-2.5 rounded-full', width)} />
                </div>
            ))}
        </div>
    )
}
