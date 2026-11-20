import { useActions, useValues } from 'kea'
import type { MouseEvent } from 'react'

import { useOpenTraceDialog } from 'products/tracing/frontend/components/TraceDialog/useOpenTraceDialog'

import { ReviewQueuePickerModal } from '../../../reviewQueues/ReviewQueuePickerModal'
import { TraceReviewButton } from '../../../traceReviews/TraceReviewButton'
import { TraceHeader } from '../components/TraceHeader'
import { traceDistributedTraceLogic } from '../traceDistributedTraceLogic'
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
    const { trace, overview } = useValues(traceViewLogic({ traceId, timestampHint }))
    const viewModel = traceViewModelLogic({ hostId, traceId, timestampHint })
    const { searchBox } = useValues(viewModel)
    const { setQuery, stepMatch } = useActions(viewModel)
    const exportLogic = traceExportLogic({ traceId, timestampHint })
    const { traceExportLoading, traceCopying } = useValues(exportLogic)
    const { exportTrace, copyTrace } = useActions(exportLogic)
    const reviewLogic = traceReviewLogic({ traceId })
    const { reviewStatus, reviewStatusFailed } = useValues(reviewLogic)
    const { loadReviewStatus } = useActions(reviewLogic)
    const { distributedTraceId } = useValues(traceDistributedTraceLogic({ traceId, timestampHint }))
    const openTraceDialog = useOpenTraceDialog()

    if (!overview) {
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
    const distributedTraceAction = distributedTraceId
        ? {
              traceId: distributedTraceId,
              // No time hint: an AI event carries its end time and a span its start, so a window around
              // one can miss the other. The trace id alone finds the spans.
              onOpen: (event: MouseEvent) =>
                  openTraceDialog(event, { traceId: distributedTraceId }, { entryPoint: 'ai_trace' }),
          }
        : undefined
    return (
        <TraceHeader
            name={overview.name}
            hasError={overview.hasError}
            backLink={backLink}
            search={trace ? { ...searchBox, onQueryChange: setQuery, onStep: stepMatch } : null}
            copyAction={trace ? { loading: traceCopying, onCopy: copyTrace } : undefined}
            exportAction={trace ? { loading: traceExportLoading, onExport: exportTrace } : undefined}
            distributedTraceAction={distributedTraceAction}
            actions={reviewActions}
        />
    )
}
