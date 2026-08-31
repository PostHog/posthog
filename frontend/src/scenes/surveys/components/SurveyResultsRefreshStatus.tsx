import { LoadingBar } from 'lib/lemon-ui/LoadingBar'

export function SurveyResultsRefreshStatus({ visible }: { visible: boolean }): JSX.Element {
    return (
        // Always reserve the height so showing the bar on requery does not push the toggles below
        // it down the page and out from under the cursor mid-click.
        <div
            className="h-2"
            aria-live="polite"
            aria-atomic="true"
            role="status"
            aria-label={visible ? 'Refreshing results' : undefined}
        >
            {visible ? (
                <LoadingBar
                    loadId="survey-results-refresh"
                    wrapperClassName="w-full max-w-none my-0"
                    className="h-1 rounded-full bg-border"
                />
            ) : null}
        </div>
    )
}
