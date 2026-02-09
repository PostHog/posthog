import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { Query } from '~/queries/Query/Query'
import { QueryBasedInsightModel } from '~/types'

import { AddJourneyModal } from './AddJourneyModal'
import { CustomerJourney, customerJourneysLogic } from './customerJourneysLogic'

function JourneyCard({
    journey,
    insight,
    onDelete,
}: {
    journey: CustomerJourney
    insight: QueryBasedInsightModel | null | undefined
    onDelete: () => void
}): JSX.Element {
    if (insight === undefined) {
        return (
            <LemonCard className="p-6">
                <Spinner />
            </LemonCard>
        )
    }

    if (!insight) {
        return (
            <LemonCard className="p-6">
                <div className="text-muted">Insight not found</div>
            </LemonCard>
        )
    }

    return (
        <LemonCard className="p-6">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="mb-1">{journey.name}</h3>
                    {journey.description && <p className="text-muted text-sm">{journey.description}</p>}
                </div>
                <LemonButton
                    icon={<IconTrash />}
                    size="small"
                    type="secondary"
                    status="danger"
                    onClick={onDelete}
                    tooltip="Remove journey"
                />
            </div>
            {insight.query && <Query query={insight.query} readOnly embedded />}
        </LemonCard>
    )
}

export function CustomerJourneys(): JSX.Element {
    const { sortedJourneys, journeysLoading, insights, insightsLoading } = useValues(customerJourneysLogic)
    const { showAddJourneyModal, deleteJourney } = useActions(customerJourneysLogic)

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
                    buttonIcon={<IconPlus />}
                    buttonTo={undefined}
                    buttonOnClick={showAddJourneyModal}
                />
                <AddJourneyModal />
            </>
        )
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h2 className="m-0">Customer journeys</h2>
                <LemonButton type="primary" icon={<IconPlus />} onClick={showAddJourneyModal}>
                    Add journey
                </LemonButton>
            </div>
            {insightsLoading ? (
                <div className="flex items-center justify-center p-8">
                    <Spinner />
                </div>
            ) : (
                <div className="space-y-4">
                    {sortedJourneys.map((journey) => (
                        <JourneyCard
                            key={journey.id}
                            journey={journey}
                            insight={insights[journey.insight]}
                            onDelete={() => deleteJourney(journey.id)}
                        />
                    ))}
                </div>
            )}
            <AddJourneyModal />
        </div>
    )
}
