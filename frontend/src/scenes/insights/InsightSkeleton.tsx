import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function InsightSkeleton(): JSX.Element {
    return (
        <>
            <div className="my-6 deprecated-space-y-4">
                <LemonSkeleton className="w-1/4 h-4" />
                <LemonSkeleton className="w-1/2 h-4" repeat={3} />
                <LemonSkeleton />
                <div className="border rounded p-6 flex items-center gap-4">
                    <div className="flex-1 deprecated-space-y-2">
                        <LemonSkeleton.Row repeat={3} />
                    </div>

                    <div className="flex-1 deprecated-space-y-2">
                        <LemonSkeleton.Row repeat={3} />
                    </div>
                </div>
                <div className="border rounded p-6 min-h-100" />
            </div>
        </>
    )
}
