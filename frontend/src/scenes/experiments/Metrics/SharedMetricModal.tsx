import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { EventsNode } from '~/queries/schema'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { SavedMetric } from '../SavedMetrics/savedMetricLogic'

export function SharedMetricModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const { savedMetrics, isPrimarySharedMetricModalOpen, isSecondarySharedMetricModalOpen } = useValues(
        experimentLogic({ experimentId })
    )
    const { closePrimarySharedMetricModal, closeSecondarySharedMetricModal, addSavedMetricToExperiment } = useActions(
        experimentLogic({ experimentId })
    )
    const [selectedMetricId, setSelectedMetricId] = useState<SavedMetric['id'] | null>(null)

    if (!savedMetrics) {
        return <></>
    }

    const isOpen = isSecondary ? isSecondarySharedMetricModalOpen : isPrimarySharedMetricModalOpen
    const closeModal = isSecondary ? closeSecondarySharedMetricModal : closePrimarySharedMetricModal

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            width={1000}
            title="Choose a metric"
            footer={
                <div className="flex justify-end gap-2">
                    <LemonButton onClick={closeModal} type="secondary">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => {
                            if (selectedMetricId) {
                                addSavedMetricToExperiment(selectedMetricId, {
                                    type: isSecondary ? 'secondary' : 'primary',
                                })
                            }
                        }}
                        type="primary"
                        disabledReason={!selectedMetricId ? 'Please select a metric' : undefined}
                    >
                        Add metric
                    </LemonButton>
                </div>
            }
        >
            <div className="flex gap-4 mb-4">
                <LemonSelect
                    options={savedMetrics.map((metric: SavedMetric) => ({
                        label: metric.name,
                        value: metric.id,
                    }))}
                    placeholder="Select a saved metric"
                    loading={false}
                    value={selectedMetricId}
                    onSelect={(value) => {
                        setSelectedMetricId(value)
                    }}
                />
            </div>

            {selectedMetricId && (
                <div className="mt-4">
                    {(() => {
                        const metric = savedMetrics.find((m: SavedMetric) => m.id === selectedMetricId)
                        if (!metric) {
                            return null
                        }

                        return (
                            <>
                                <h4 className="font-semibold">{metric.name}</h4>

                                {metric.description && <p className="mt-2">{metric.description}</p>}

                                {metric.query.kind === 'ExperimentTrendsQuery' && (
                                    <div className="mt-2">
                                        <span className="font-semibold">Event:</span>{' '}
                                        {metric.query.count_query.series[0].event}
                                    </div>
                                )}

                                {metric.query.kind === 'ExperimentFunnelsQuery' && (
                                    <div className="mt-2">
                                        <span className="font-semibold">Funnel steps:</span>
                                        <ol className="list-decimal ml-6 mt-1">
                                            {/* TODO THIS MIGHT FAIL FOR ACTIONS */}
                                            {metric.query.funnels_query.series.map(
                                                (item: EventsNode, index: number) => (
                                                    <li key={index}>{item?.event}</li>
                                                )
                                            )}
                                        </ol>
                                    </div>
                                )}
                            </>
                        )
                    })()}
                </div>
            )}
        </LemonModal>
    )
}
