import { Skeleton } from '@posthog/quill'

export function PieLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 items-center justify-center" aria-busy="true">
            <Skeleton className="aspect-square h-4/5 max-h-full rounded-full" />
        </div>
    )
}
