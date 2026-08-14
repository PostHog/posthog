import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonCollapse } from '@posthog/lemon-ui'

import { FeatureRequestHistory } from './FeatureRequestHistory'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestHistorySection({ requestId }: { requestId: string }): JSX.Element {
    const { requestHistory, requestHistoryLoading, requestHistoryError, requestHistoryShowingAll } =
        useValues(featureRequestsLogic)
    const { loadRequestHistory, setRequestHistoryShowingAll } = useActions(featureRequestsLogic)
    const title = requestHistoryLoading ? 'History' : `History (${requestHistory.length})`

    return (
        <LemonCollapse
            embedded
            size="small"
            defaultActiveKey="history"
            panels={[
                {
                    key: 'history',
                    dataAttr: 'feature-request-history-collapse',
                    header: {
                        type: 'tertiary',
                        className: '!px-0',
                        children: (
                            <span className="flex items-center gap-2 font-semibold">
                                <IconClock className="size-4 text-secondary" />
                                {title}
                            </span>
                        ),
                    },
                    className: '!px-0 !pb-0 !pt-3',
                    content: (
                        <FeatureRequestHistory
                            history={requestHistory}
                            loading={requestHistoryLoading}
                            error={requestHistoryError}
                            showingAll={requestHistoryShowingAll}
                            onRetry={() => loadRequestHistory(requestId)}
                            onSetShowingAll={setRequestHistoryShowingAll}
                        />
                    ),
                },
            ]}
        />
    )
}
