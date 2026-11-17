import { useActions, useValues } from 'kea'

import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@posthog/quill'

import { CHECKS_CONTAINER } from './checkTableLayout'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import { QuillSuiteRunsHistory } from './QuillSuiteRunsHistory'

export function QuillRunHistoryDialog(props: DataQualityChecksLogicProps): JSX.Element {
    const logic = dataQualityChecksLogic(props)
    const { runHistoryOpen } = useValues(logic)
    const { closeRunHistory } = useActions(logic)

    return (
        <Dialog
            open={runHistoryOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeRunHistory()
                }
            }}
        >
            <DialogContent size="wide" data-attr="data-quality-run-history-dialog">
                <DialogHeader>
                    <DialogTitle>Check run history</DialogTitle>
                    <DialogDescription>
                        Results from checks run together. Expand a run to see each check's result.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className={CHECKS_CONTAINER}>
                        <QuillSuiteRunsHistory {...props} />
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
