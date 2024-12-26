import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { MetricDisplayFunnels, MetricDisplayTrends } from '../ExperimentView/Goal'
import { SavedMetric } from '../SavedMetrics/savedMetricLogic'

export function SavedMetricModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const { savedMetrics, isPrimarySavedMetricModalOpen, isSecondarySavedMetricModalOpen, editingSavedMetricId } =
        useValues(experimentLogic({ experimentId }))
    const {
        closePrimarySavedMetricModal,
        closeSecondarySavedMetricModal,
        addSavedMetricToExperiment,
        removeSavedMetricFromExperiment,
    } = useActions(experimentLogic({ experimentId }))

    const [selectedMetricId, setSelectedMetricId] = useState<SavedMetric['id'] | null>(null)
    useEffect(() => {
        if (editingSavedMetricId) {
            setSelectedMetricId(editingSavedMetricId)
        }
    }, [editingSavedMetricId])

    if (!savedMetrics) {
        return <></>
    }

    const isOpen = isSecondary ? isSecondarySavedMetricModalOpen : isPrimarySavedMetricModalOpen
    const closeModal = isSecondary ? closeSecondarySavedMetricModal : closePrimarySavedMetricModal

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            width={1000}
            title="Choose a metric"
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {editingSavedMetricId && (
                            <LemonButton
                                status="danger"
                                onClick={() => {
                                    removeSavedMetricFromExperiment(editingSavedMetricId)
                                }}
                                type="secondary"
                            >
                                Remove from experiment
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-2">
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
                            console.error('Metric not found', savedMetrics, selectedMetricId)
                            return null
                        }

                        return (
                            <>
                                <h3 className="font-semibold">{metric.name}</h3>
                                {metric.description && <p className="mt-2">{metric.description}</p>}
                                {metric.query.kind === 'ExperimentTrendsQuery' && (
                                    <MetricDisplayTrends query={metric.query.count_query} />
                                )}
                                {metric.query.kind === 'ExperimentFunnelsQuery' && (
                                    <MetricDisplayFunnels query={metric.query.funnels_query} />
                                )}
                            </>
                        )
                    })()}
                </div>
            )}
        </LemonModal>
    )
}
