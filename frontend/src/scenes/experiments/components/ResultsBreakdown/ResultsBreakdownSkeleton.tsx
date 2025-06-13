import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

export const ResultsBreakdownSkeleton = (): JSX.Element => {
    return (
        <div className="space-y-4">
            <div className="border rounded-lg p-4 bg-bg-light space-y-3">
                <div className="flex flex-col items-center gap-3">
                    <span className="text-muted font-semibold text-base">Loading breakdown</span>
                    <Spinner className="text-xl text-muted" />
                </div>
            </div>
        </div>
    )
}
