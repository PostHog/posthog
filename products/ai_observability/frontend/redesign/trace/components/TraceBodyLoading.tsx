import { LemonSkeleton } from '@posthog/lemon-ui'

export function TraceBodyLoading(): JSX.Element {
    return (
        <div className="flex flex-col gap-3" role="status" aria-busy="true" aria-label="Loading trace">
            <LemonSkeleton className="h-8 w-60" />
            <div className="@container">
                <div className="flex flex-col gap-4 @3xl:flex-row">
                    <div className="flex w-full shrink-0 flex-col gap-2 @3xl:w-72">
                        <LemonSkeleton repeat={5} className="h-8" />
                    </div>
                    <LemonSkeleton className="h-64 min-h-64 min-w-0 flex-1" />
                </div>
            </div>
        </div>
    )
}
