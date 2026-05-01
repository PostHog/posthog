import { LoadingBar } from 'lib/lemon-ui/LoadingBar'

export function SurveyResultsRefreshStatus({ visible }: { visible: boolean }): JSX.Element {
    return (
        <div
            className={visible ? 'h-2' : 'h-0'}
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
