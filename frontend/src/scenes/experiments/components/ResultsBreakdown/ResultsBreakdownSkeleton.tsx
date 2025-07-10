import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

export const ResultsBreakdownSkeleton = (): JSX.Element => {
    /**
     * this is matching the styles of ChartLoadingState.tsx. Why not reuse that component?
     * it takes a height prop, but we don't need it here.
     */
    return (
        <div className="space-y-4">
            <div className="bg-bg-light space-y-3 rounded-lg border p-4">
                <div className="flex items-center justify-center gap-2 font-normal">
                    <Spinner className="text-lg" />
                    <span>Loading breakdown</span>
                </div>
            </div>
        </div>
    )
}
