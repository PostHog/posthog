import { IconCheck, IconX } from '@posthog/icons'

export function NoResultEmptyState({ error }: { error: any }): JSX.Element {
    if (!error) {
        return <></>
    }

    type ErrorCode = 'no-events' | 'no-flag-info' | 'no-control-variant' | 'no-test-variant' | 'no-exposures'

    const { statusCode, hasDiagnostics } = error

    function ChecklistItem({ errorCode, value }: { errorCode: ErrorCode; value: boolean }): JSX.Element {
        const failureText = {
            'no-events': 'Metric events not received',
            'no-flag-info': 'Feature flag information not present on the events',
            'no-control-variant': 'Events with the control variant not received',
            'no-test-variant': 'Events with at least one test variant not received',
            'no-exposures': 'Exposure events not received',
        }

        const successText = {
            'no-events': 'Experiment events have been received',
            'no-flag-info': 'Feature flag information is present on the events',
            'no-control-variant': 'Events with the control variant received',
            'no-test-variant': 'Events with at least one test variant received',
            'no-exposures': 'Exposure events have been received',
        }

        return (
            <div className="flex items-center space-x-2">
                {value === false ? (
                    <span className="flex items-center space-x-2">
                        <IconCheck className="text-success" fontSize={16} />
                        <span className="text-muted">{successText[errorCode]}</span>
                    </span>
                ) : (
                    <span className="flex items-center space-x-2">
                        <IconX className="text-danger" fontSize={16} />
                        <span>{failureText[errorCode]}</span>
                    </span>
                )}
            </div>
        )
    }

    if (hasDiagnostics) {
        const checklistItems = []
        for (const [errorCode, value] of Object.entries(error.detail as Record<ErrorCode, boolean>)) {
            checklistItems.push(<ChecklistItem key={errorCode} errorCode={errorCode as ErrorCode} value={value} />)
        }

        return <div>{checklistItems}</div>
    }

    if (statusCode === 504) {
        return (
            <>
                <h2 className="text-xl font-semibold leading-tight">Experiment results timed out</h2>
                <div className="text-sm text-center text-balance">
                    This may occur when the experiment has a large amount of data or is particularly complex. We are
                    actively working on fixing this. In the meantime, please try refreshing the experiment to retrieve
                    the results.
                </div>
            </>
        )
    }

    // Other unexpected errors
    return <div>{error.detail}</div>
}
