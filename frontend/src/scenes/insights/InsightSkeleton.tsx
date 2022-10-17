import { LemonSkeleton } from 'lib/components/LemonSkeleton'

export function InsightSkeleton(): JSX.Element {
    return (
        <>
            <div className="my-6 space-y-4">
                <LemonSkeleton className="w-1/4" />
                <LemonSkeleton className="w-1/2" repeat={3} />
                <LemonSkeleton />
                <div className="border rounded p-6 flex items-center gap-4">
                    <div className="flex-1 space-y-2">
                        <LemonSkeleton.Row repeat={3} />
                    </div>

                    <div className="flex-1 space-y-2">
                        <LemonSkeleton.Row repeat={3} />
                    </div>
                </div>
                <div className="border rounded p-6" style={{ minHeight: 600 }} />
            </div>
        </>
    )
}
