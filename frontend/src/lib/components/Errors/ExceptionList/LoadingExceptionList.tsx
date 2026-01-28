import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export function LoadingExceptionList({ className }: { className?: string }): JSX.Element {
    return (
        <div className={cn('flex flex-col gap-y-2', className)}>
            <LemonSkeleton className="h-5 w-1/2" />
            <LemonSkeleton className="h-4 w-full" />
        </div>
    )
}
