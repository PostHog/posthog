import { LoadingBar } from 'lib/lemon-ui/LoadingBar'

export function SurveyResultsRefreshStatus({ visible }: { visible: boolean }): JSX.Element {
    return (
        // Overlay the bar instead of reserving height, so starting a requery never changes the
        // layout and pushes the toggles below it down out from under the cursor mid-click.
        <div
            className="relative h-0"
            aria-live="polite"
            aria-atomic="true"
            role="status"
            aria-label={visible ? 'Refreshing results' : undefined}
        >
            {visible ? (
                <LoadingBar
                    loadId="survey-results-refresh"
                    wrapperClassName="absolute inset-x-0 top-0 z-10 w-full max-w-none my-0"
                    className="h-1 rounded-full bg-border"
                />
            ) : null}
        </div>
    )
}
