import { useActions, useValues } from 'kea'

import { ReviewQueuePickerModal } from '../../../reviewQueues/ReviewQueuePickerModal'
import { TraceReviewButton } from '../../../traceReviews/TraceReviewButton'
import { TraceHeader } from '../components/TraceHeader'
import { traceExportLogic } from '../traceExportLogic'
import { traceReviewLogic } from '../traceReviewLogic'
import { traceViewLogic } from '../traceViewLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { LabeledLink, TraceViewKey } from '../types'

export interface TraceHeaderHostProps extends TraceViewKey {
    backLink: LabeledLink | null
}

export function TraceHeaderHost({
    hostId,
    traceId,
    timestampHint,
    backLink,
}: TraceHeaderHostProps): JSX.Element | null {
    const { trace } = useValues(traceViewLogic({ traceId, timestampHint }))
    const viewModel = traceViewModelLogic({ hostId, traceId, timestampHint })
    const { searchBox } = useValues(viewModel)
    const { setQuery, stepMatch } = useActions(viewModel)
    const exportLogic = traceExportLogic({ traceId, timestampHint })
    const { traceExportLoading, traceCopying } = useValues(exportLogic)
    const { exportTrace, copyTrace } = useActions(exportLogic)
    const reviewLogic = traceReviewLogic({ traceId })
    const { reviewStatus, reviewStatusFailed } = useValues(reviewLogic)
    const { loadReviewStatus } = useActions(reviewLogic)

    if (!trace) {
        return null
    }
    const queue = reviewStatus?.queue ?? null
    // No queue id goes to the review button: saving a review then clears whichever queue holds the trace, so a stale
    // status can never point the save at the wrong queue.
    const reviewActions =
        reviewStatus || reviewStatusFailed ? (
            <>
                <TraceReviewButton
                    traceId={traceId}
                    buttonType="secondary"
                    buttonSize="small"
                    buttonLabel={reviewStatus ? (reviewStatus.review ? 'Edit review' : 'Review') : undefined}
                />
                {reviewStatus && !reviewStatusFailed && !reviewStatus.review ? (
                    <ReviewQueuePickerModal
                        traceId={traceId}
                        queueItemId={queue?.itemId ?? null}
                        defaultQueueId={queue?.id ?? null}
                        confirmLabel={queue ? 'Change queue' : 'Add to queue'}
                        buttonType="secondary"
                        buttonSize="small"
                        onSuccess={() => loadReviewStatus()}
                    />
                ) : null}
            </>
        ) : null
    return (
        <TraceHeader
            name={trace.name}
            hasError={trace.hasError}
            backLink={backLink}
            search={{ ...searchBox, onQueryChange: setQuery, onStep: stepMatch }}
            copyAction={{ loading: traceCopying, onCopy: copyTrace }}
            exportAction={{ loading: traceExportLoading, onExport: exportTrace }}
            actions={reviewActions}
        />
    )
}
