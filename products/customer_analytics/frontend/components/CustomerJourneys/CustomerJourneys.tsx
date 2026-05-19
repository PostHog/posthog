import { useActions, useMountedLogic, useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { Query } from '~/queries/Query/Query'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { CustomerJourneysEmptyState } from './CustomerJourneysEmptyState'
import { customerJourneysLogic } from './customerJourneysLogic'

export function CustomerJourneys(): JSX.Element {
    const mountedSceneLogic = useMountedLogic(customerAnalyticsSceneLogic)
    const mountedCustomerJourneysLogic = customerJourneysLogic()
    const { journeyOptions, journeysLoading, activeInsightLoading, activeJourneyFullQuery } =
        useValues(mountedCustomerJourneysLogic)
    const { setQueryOverride } = useActions(mountedCustomerJourneysLogic)
    useAttachedLogic(mountedCustomerJourneysLogic, mountedSceneLogic)

    if (journeysLoading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner />
            </div>
        )
    }

    if (journeyOptions.length === 0) {
        return (
            <>
                <CustomerJourneysEmptyState />
            </>
        )
    }

    return (
        <div className="space-y-4">
            {activeInsightLoading ? (
                <div className="flex items-center justify-center p-8">
                    <Spinner />
                </div>
            ) : activeJourneyFullQuery ? (
                <Query query={activeJourneyFullQuery} setQuery={setQueryOverride} readOnly />
            ) : (
                <div className="text-muted text-center p-8">Insight not found</div>
            )}
        </div>
    )
}
