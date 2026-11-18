import { Skeleton } from '@posthog/quill'

export function QuillLoadingState(): JSX.Element {
    return (
        <div className="flex flex-col gap-4" data-attr="experiment-loading">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-4 w-2/3" />
        </div>
    )
}
