import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function InsightSkeleton(): JSX.Element {
    return (
        <>
            <div className="deprecated-space-y-4 my-6">
                <LemonSkeleton className="h-4 w-1/4" />
                <LemonSkeleton className="h-4 w-1/2" repeat={3} />
                <LemonSkeleton />
                <div className="flex items-center gap-4 rounded border p-6">
                    <div className="deprecated-space-y-2 flex-1">
                        <LemonSkeleton.Row repeat={3} />
                    </div>

                    <div className="deprecated-space-y-2 flex-1">
                        <LemonSkeleton.Row repeat={3} />
                    </div>
                </div>
                <div className="min-h-100 rounded border p-6" />
            </div>
        </>
    )
}
