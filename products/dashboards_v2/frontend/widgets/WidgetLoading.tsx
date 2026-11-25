import { Skeleton } from '@posthog/quill'

export function WidgetLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col" aria-busy="true">
            <Skeleton className="h-full w-full" />
        </div>
    )
}
