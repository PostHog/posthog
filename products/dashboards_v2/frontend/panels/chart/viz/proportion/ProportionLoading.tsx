import { Skeleton } from '@posthog/quill'

export function ProportionLoading(): JSX.Element {
    return (
        <div className="flex flex-col gap-2" aria-busy="true">
            <Skeleton className="h-6 w-full" />
            <div className="flex gap-4">
                {Array.from({ length: 3 }, (_, index) => (
                    <Skeleton key={index} className="h-2 w-20" />
                ))}
            </div>
        </div>
    )
}
