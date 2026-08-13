import { LemonSkeleton } from '@posthog/lemon-ui'

export function FeatureRequestDetailSkeleton(): JSX.Element {
    return (
        <div
            className="@container w-full max-w-6xl mx-auto px-6 py-5 text-sm"
            role="status"
            aria-label="Loading feature request"
        >
            <div className="flex flex-col gap-3 mb-6 pb-5 border-b border-primary" aria-hidden>
                <LemonSkeleton className="h-7 w-32 rounded" />
                <LemonSkeleton className="h-6 w-2/3 max-w-xl rounded" />
                <LemonSkeleton className="h-5 w-48 rounded" />
            </div>
            <div className="grid grid-cols-1 @5xl:grid-cols-3 gap-6" aria-hidden>
                <div className="flex flex-col gap-3 @5xl:col-span-2">
                    <LemonSkeleton className="h-4 w-28 rounded" />
                    <LemonSkeleton className="h-3 w-full rounded" />
                    <LemonSkeleton className="h-3 w-11/12 rounded" />
                    <LemonSkeleton className="h-3 w-4/5 rounded" />
                </div>
                <div className="flex flex-col gap-4">
                    <LemonSkeleton className="h-16 w-full rounded" />
                    <LemonSkeleton className="h-12 w-full rounded" />
                    <LemonSkeleton className="h-24 w-full rounded" />
                </div>
            </div>
        </div>
    )
}
