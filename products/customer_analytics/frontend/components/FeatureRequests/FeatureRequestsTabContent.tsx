import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FeatureRequestDetail } from './FeatureRequestDetail'
import { FeatureRequestDetailSkeleton } from './FeatureRequestDetailSkeleton'
import { FeatureRequestList } from './FeatureRequestList'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestsTabContent(): JSX.Element {
    const { activeRequest, activeRequestLoading, activeRequestError, activeRequestId } = useValues(featureRequestsLogic)
    const { loadActiveRequest } = useActions(featureRequestsLogic)

    if (!activeRequestId) {
        return <FeatureRequestList />
    }
    if (activeRequestError) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadActiveRequest(activeRequestId) }}
            >
                {activeRequestError}
            </LemonBanner>
        )
    }
    if (activeRequestLoading || !activeRequest) {
        return <FeatureRequestDetailSkeleton />
    }
    return <FeatureRequestDetail request={activeRequest} />
}
