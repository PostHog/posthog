import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export interface BlastRadiusSkeletonProps {
    /** Plural aggregation target name, e.g. "users" or "organizations". */
    targetName: string
}

/**
 * Holds the space of the loaded blast-radius summary (two lines of counts and the matching actors link),
 * so the controls below a release condition do not move when the counts arrive.
 */
export function BlastRadiusSkeleton({ targetName }: BlastRadiusSkeletonProps): JSX.Element {
    return (
        <div role="status" aria-label={`Calculating affected ${targetName}`} className="flex flex-col">
            <div className="h-lh flex items-center">
                <LemonSkeleton className="h-3 w-40" />
            </div>
            <div className="h-lh flex items-center">
                <LemonSkeleton className="h-3 w-52" />
            </div>
            {/* Keep mt-1 in sync with the top margin of MatchingActorsLink, so that both states have the same height */}
            <div className="h-lh flex items-center mt-1">
                <LemonSkeleton className="h-3 w-32" />
            </div>
        </div>
    )
}
