import { Skeleton } from '@posthog/quill'

export function QuillSavedInsightsTableSkeleton(): JSX.Element {
    return (
        <div aria-busy aria-label="Loading insights" className="flex flex-col gap-3 p-3">
            {Array.from({ length: 6 }, (_, index) => (
                <div key={index} className="flex items-center gap-3">
                    <Skeleton className="size-4 shrink-0" />
                    <Skeleton className={index % 2 === 0 ? 'h-3 w-56' : 'h-3 w-40'} />
                    <Skeleton className="ml-auto h-3 w-20" />
                </div>
            ))}
        </div>
    )
}
