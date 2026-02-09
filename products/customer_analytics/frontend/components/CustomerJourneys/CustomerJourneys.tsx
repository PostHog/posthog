import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { Query } from '~/queries/Query/Query'
import { isInsightVizNode } from '~/queries/utils'

import { AddJourneyModal } from './AddJourneyModal'
import { customerJourneysLogic } from './customerJourneysLogic'

export function CustomerJourneys(): JSX.Element {
    const { sortedJourneys, journeysLoading, activeJourney, activeJourneyId, activeInsight, activeInsightLoading } =
        useValues(customerJourneysLogic)
    const { showAddJourneyModal, setActiveJourneyId, deleteJourney } = useActions(customerJourneysLogic)

    if (journeysLoading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner />
            </div>
        )
    }

    if (sortedJourneys.length === 0) {
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

    const journeyOptions = sortedJourneys.map((j) => ({
        value: j.id,
        label: j.name,
    }))

    const query = activeInsight?.query
    const fullQuery = query && isInsightVizNode(query) ? { ...query, full: true } : query

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
            ) : fullQuery ? (
                <Query query={fullQuery} readOnly />
            ) : (
                <div className="text-muted text-center p-8">Insight not found</div>
            )}

            <AddJourneyModal />
        </div>
    )
}
