import { LemonSkeleton } from '@posthog/lemon-ui'

export function LoadingState(): JSX.Element {
    return (
        <div className="deprecated-space-y-4">
            <LemonSkeleton className="w-1/3 h-4" />
            <LemonSkeleton />
            <LemonSkeleton />
            <LemonSkeleton className="w-2/3 h-4" />
        </div>
    )
}
