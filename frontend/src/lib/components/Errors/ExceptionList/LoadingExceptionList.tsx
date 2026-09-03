import { Skeleton } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

export function LoadingExceptionList({ className }: { className?: string }): JSX.Element {
    return (
        <div className={cn('flex flex-col gap-y-2', className)}>
            <Skeleton className="h-5 w-1/2">
                <span>Loading…</span>
            </Skeleton>
            <Skeleton className="h-4 w-full">
                <span>Loading…</span>
            </Skeleton>
        </div>
    )
}
