import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

export function MaterializationLoading(): JSX.Element {
    return (
        <div className="space-y-6" aria-busy="true" data-attr="materialization-loading">
            <LemonCard className="!p-3 w-fit max-w-full">
                <div className="flex items-center gap-3 mb-3">
                    <LemonSkeleton className="h-5 w-20" />
                    <LemonSkeleton className="h-6 w-24" />
                </div>
                <div className="flex flex-wrap gap-4">
                    <LemonSkeleton className="h-5 w-44" />
                    <LemonSkeleton className="h-5 w-32" />
                </div>
            </LemonCard>
            <div className="space-y-3">
                <LemonSkeleton className="h-5 w-32" />
                <LemonSkeleton className="h-10 w-full max-w-96" />
            </div>
            <div className="space-y-3">
                <LemonSkeleton className="h-5 w-28" />
                <LemonSkeleton className="h-5 w-full max-w-80" />
                <LemonSkeleton className="h-5 w-full max-w-96" />
            </div>
            <div className="border-t pt-6 space-y-3">
                <LemonSkeleton className="h-6 w-28" />
                <LemonSkeleton className="h-10 w-full" />
                <LemonSkeleton className="h-10 w-full" />
            </div>
        </div>
    )
}
