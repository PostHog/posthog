import { Skeleton } from '@posthog/quill'

export function TodayRowsSkeleton(): JSX.Element {
    return (
        <ol className="TodayRows" aria-busy aria-label="Loading">
            {['w-3/5', 'w-4/5', 'w-1/2'].map((width) => (
                <li key={width} className="TodayRow">
                    <Skeleton className="TodayRow__iconSkeleton" />
                    <div className="flex flex-col gap-2 py-1">
                        <Skeleton className={`h-3.5 ${width}`} />
                        <Skeleton className="h-3 w-2/5" />
                    </div>
                </li>
            ))}
        </ol>
    )
}
