import { LemonSkeleton } from '@posthog/lemon-ui'

export function BatchExportLoadingSkeleton(): JSX.Element {
    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <LemonSkeleton className="w-20 h-8" fade />
                <LemonSkeleton className="w-32 h-10" fade />
            </div>
            <LemonSkeleton className="w-full h-96" fade />
        </div>
    )
}
