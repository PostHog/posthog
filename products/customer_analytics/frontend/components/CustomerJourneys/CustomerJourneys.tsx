import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { Query } from '~/queries/Query/Query'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { AddJourneyModal } from './AddJourneyModal'
import { customerJourneysLogic } from './customerJourneysLogic'

export function CustomerJourneys(): JSX.Element {
    const mountedSceneLogic = useMountedLogic(customerAnalyticsSceneLogic)
    const mountedCustomerJourneysLogic = customerJourneysLogic()
    useAttachedLogic(mountedCustomerJourneysLogic, mountedSceneLogic)
    const {
        journeyOptions,
        journeysLoading,
        activeJourney,
        activeJourneyId,
        activeInsightLoading,
        activeJourneyFullQuery,
    } = useValues(mountedCustomerJourneysLogic)
    const { showAddJourneyModal, setActiveJourneyId, deleteJourney } = useActions(mountedCustomerJourneysLogic)

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
                <EmptyMessage
                    title="No customer journeys yet"
                    description="Add existing funnel insights as customer journeys to track how customers move through your product."
                    buttonText="Add a funnel"
                    buttonOnClick={showAddJourneyModal}
                />
                <AddJourneyModal />
            </>
        )
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <LemonSelect
                    value={activeJourneyId}
                    onChange={setActiveJourneyId}
                    options={journeyOptions}
                    size="small"
                />
                <LemonButton type="secondary" icon={<IconPlus />} size="small" onClick={showAddJourneyModal}>
                    Add journey
                </LemonButton>
                {activeJourney && (
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        type="secondary"
                        status="danger"
                        onClick={() => deleteJourney(activeJourney.id)}
                        tooltip="Remove this journey"
                    />
                )}
            </div>

            {activeInsightLoading ? (
                <div className="flex items-center justify-center p-8">
                    <Spinner />
                </div>
            ) : activeJourneyFullQuery ? (
                <Query query={activeJourneyFullQuery} readOnly />
            ) : (
                <div className="text-muted text-center p-8">Insight not found</div>
            )}

            <AddJourneyModal />
        </div>
    )
}
