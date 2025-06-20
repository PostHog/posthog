import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

export const ResultsBreakdownSkeleton = (): JSX.Element | null => {
    const isEnabled = useFeatureFlag('EXPERIMENTS_NEW_RUNNER_RESULTS_BREAKDOWN')

    if (!isEnabled) {
        return null
    }

    /**
     * this is matching the styles of ChartLoadingState.tsx. Why not reuse that component?
     * it takes a height prop, but we don't need it here.
     */
    return (
        <div className="space-y-4">
            <div className="border rounded-lg p-4 bg-bg-light space-y-3">
                <div className="flex items-center justify-center gap-2 font-normal">
                    <Spinner className="text-lg" />
                    <span>Loading breakdown</span>
                </div>
            </div>
        </div>
    )
}
