import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'

import { FeatureRequestDetailSection } from './FeatureRequestDetailSection'
import { FeatureRequestHistory } from './FeatureRequestHistory'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestHistorySection({ requestId }: { requestId: string }): JSX.Element {
    const { requestHistory, requestHistoryLoading, requestHistoryError, requestHistoryShowingAll } =
        useValues(featureRequestsLogic)
    const { loadRequestHistory, setRequestHistoryShowingAll, showHistoryTarget } = useActions(featureRequestsLogic)

    return (
        <FeatureRequestDetailSection
            icon={<IconClock />}
            title="History"
            collapsible
            dataAttr="feature-request-history-collapse"
            meta={
                requestHistoryLoading ? null : (
                    <span className="text-xs text-tertiary tabular-nums">
                        {requestHistory.length} {requestHistory.length === 1 ? 'entry' : 'entries'}
                    </span>
                )
            }
        >
            <FeatureRequestHistory
                history={requestHistory}
                loading={requestHistoryLoading}
                error={requestHistoryError}
                showingAll={requestHistoryShowingAll}
                onRetry={() => loadRequestHistory(requestId)}
                onSetShowingAll={setRequestHistoryShowingAll}
                onShowTarget={showHistoryTarget}
            />
        </FeatureRequestDetailSection>
    )
}
