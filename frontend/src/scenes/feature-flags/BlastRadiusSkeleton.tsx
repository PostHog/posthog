import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'

import { MatchingActorsLink } from './MatchingActorsLink'

export interface BlastRadiusSkeletonProps {
    /** Plural aggregation target name, e.g. "users" or "organizations". */
    targetName: string
}

/**
 * Holds the space of the loaded blast-radius summary, so the controls below a release condition do not
 * move when the counts arrive. It renders the summary's own markup under the shimmer, so the reserved
 * height follows the summary's typography and the link's margin without a copied layout.
 */
export function BlastRadiusSkeleton({ targetName }: BlastRadiusSkeletonProps): JSX.Element {
    return (
        <div role="status" className="flex flex-col">
            <span className="sr-only">Calculating affected {targetName}…</span>
            <WrappingLoadingSkeleton>
                {/* `inert` keeps the hidden link out of the tab order; React 18 types lack the attribute */}
                <div className="flex flex-col" {...{ inert: '' }}>
                    <span>Filters match: ~0 {targetName}</span>
                    <span>Rollout will be to ~0 {targetName} - 100%</span>
                    <MatchingActorsLink properties={undefined} resolvedGroupTypeIndex={null} targetName={targetName} />
                </div>
            </WrappingLoadingSkeleton>
        </div>
    )
}
