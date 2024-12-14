import { IconArchive } from '@posthog/icons'
import { IconCheck, IconX } from '@posthog/icons'

export function NoResultEmptyState({ error }: { error: any }): JSX.Element {
    if (!error) {
        return <></>
    }

    type ErrorCode = 'no-events' | 'no-flag-info' | 'no-control-variant' | 'no-test-variant'

    const { statusCode } = error

    function ChecklistItem({ errorCode, value }: { errorCode: ErrorCode; value: boolean }): JSX.Element {
        const failureText = {
            'no-events': 'Metric events not received',
            'no-flag-info': 'Feature flag information not present on the events',
            'no-control-variant': 'Events with the control variant not received',
            'no-test-variant': 'Events with at least one test variant not received',
        }

        const successText = {
            'no-events': 'Experiment events have been received',
            'no-flag-info': 'Feature flag information is present on the events',
            'no-control-variant': 'Events with the control variant received',
            'no-test-variant': 'Events with at least one test variant received',
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

    // Validation errors return 400 and are rendered as a checklist
    if (statusCode === 400) {
        let parsedDetail: Record<ErrorCode, boolean>
        try {
            parsedDetail = JSON.parse(error.detail)
        } catch (error) {
            return (
                <div className="border rounded bg-bg-light p-4">
                    <div className="font-semibold leading-tight text-base text-current">
                        Experiment results could not be calculated
                    </div>
                    <div className="mt-2">{error}</div>
                </div>
            )
        }

        const checklistItems = []
        for (const [errorCode, value] of Object.entries(parsedDetail)) {
            checklistItems.push(<ChecklistItem key={errorCode} errorCode={errorCode as ErrorCode} value={value} />)
        }

        return <div>{checklistItems}</div>
    }

    if (statusCode === 504) {
        return (
            <div>
                <div className="border rounded bg-bg-light py-10">
                    <div className="flex flex-col items-center mx-auto text-muted space-y-2">
                        <IconArchive className="text-4xl text-secondary-3000" />
                        <h2 className="text-xl font-semibold leading-tight">Experiment results timed out</h2>
                        <div className="text-sm text-center text-balance">
                            This may occur when the experiment has a large amount of data or is particularly complex. We
                            are actively working on fixing this. In the meantime, please try refreshing the experiment
                            to retrieve the results.
                        </div>
                    </div>
                </div>
            </div>
        )
    }

    // Other unexpected errors
    return (
        <div>
            <div className="border rounded bg-bg-light py-10">
                <div className="flex flex-col items-center mx-auto text-muted space-y-2">
                    <IconArchive className="text-4xl text-secondary-3000" />
                    <h2 className="text-xl font-semibold leading-tight">Experiment results could not be calculated</h2>
                    <div className="text-sm text-center text-balance">{error.detail}</div>
                </div>
            </div>
        </div>
    )
}
