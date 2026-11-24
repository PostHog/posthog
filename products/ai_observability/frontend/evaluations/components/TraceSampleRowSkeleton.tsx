import { LemonSkeleton } from '@posthog/lemon-ui'

/** A `TraceSampleRow` while its trace preview loads. */
export function TraceSampleRowSkeleton(): JSX.Element {
    return (
        <div className="flex items-start gap-3 px-3 py-2.5">
            <LemonSkeleton className="size-6 rounded-full" />
            <div className="flex flex-1 flex-col gap-1.5">
                <LemonSkeleton className="h-4 w-3/4" />
                <LemonSkeleton className="h-3 w-1/2" />
            </div>
        </div>
    )
}
