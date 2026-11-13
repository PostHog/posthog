import { useActions, useValues } from 'kea'

import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import { QuillCheckCallout } from './QuillCheckCallout'

export function QuillChecksPanelBanners(props: DataQualityChecksLogicProps): JSX.Element {
    const logic = dataQualityChecksLogic(props)
    const { checksLoadError, isSuiteRunning, pollTimedOut } = useValues(logic)
    const { loadChecks, loadHealth } = useActions(logic)

    return (
        <>
            {checksLoadError && (
                <QuillCheckCallout tone="warning" action={{ label: 'Retry', onClick: loadChecks }}>
                    Could not refresh the checks. Showing the latest available results.
                </QuillCheckCallout>
            )}
            {isSuiteRunning && (
                <QuillCheckCallout tone="info" busy>
                    Running checks...
                </QuillCheckCallout>
            )}
            {pollTimedOut && (
                <QuillCheckCallout
                    tone="warning"
                    action={{
                        label: 'Refresh',
                        onClick: () => {
                            loadChecks()
                            loadHealth()
                        },
                    }}
                >
                    Checks are still running. Check back in a few minutes.
                </QuillCheckCallout>
            )}
        </>
    )
}
