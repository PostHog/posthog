import { Skeleton, SkeletonText } from '@posthog/quill'

const INTRO_LINES = 2
const STEP_COUNT = 3

/** The page's shape while the submission loads: the hero, then the three steps. */
export function TranscriptPageSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-8" aria-busy data-attr="agent-transcript-loading">
            <div className="flex flex-col items-center gap-3">
                <Skeleton className="size-24 rounded-full @min-[32rem]/agent-transcript:size-32" />
                <Skeleton className="h-8 w-full max-w-sm" />
                <SkeletonText lines={INTRO_LINES} className="w-full max-w-lg" />
            </div>
            <div className="flex flex-col gap-3">
                {Array.from({ length: STEP_COUNT }, (_, index) => (
                    <Skeleton key={index} className="h-32 w-full rounded-lg" />
                ))}
            </div>
        </div>
    )
}
