import { Skeleton } from '@posthog/quill'

export function QuillTableLoadingRows(): JSX.Element {
    return (
        <div className="flex flex-col gap-2" aria-busy>
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
        </div>
    )
}
