import { LemonButton, LemonModal, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

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
    const [mode, setMode] = useState<'create' | 'edit'>('create')

    useEffect(() => {
        if (editingSavedMetricId) {
            setSelectedMetricId(editingSavedMetricId)
            setMode('edit')
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
            width={500}
            title={mode === 'create' ? 'Select a shared metric' : 'Shared metric'}
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
                        {/* Changing the existing metric is a pain because saved metrics are stored separately */}
                        {/* Only allow deletion for now */}
                        {mode === 'create' && (
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
                        )}
                    </div>
                </div>
            }
        >
            {mode === 'create' && (
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
            )}

            {selectedMetricId && (
                <div>
                    {(() => {
                        const metric = savedMetrics.find((m: SavedMetric) => m.id === selectedMetricId)
                        if (!metric) {
                            return <></>
                        }

                        return (
                            <div className="space-y-2">
                                <div className="flex items-center gap-2">
                                    <h3 className="font-semibold m-0 flex items-center">{metric.name}</h3>
                                    <Link
                                        target="_blank"
                                        className="font-semibold flex items-center"
                                        to={urls.experimentsSavedMetric(metric.id)}
                                    >
                                        <IconOpenInNew fontSize="18" />
                                    </Link>
                                </div>
                                {metric.description && <p className="mt-2">{metric.description}</p>}
                                {metric.query.kind === 'ExperimentTrendsQuery' && (
                                    <MetricDisplayTrends query={metric.query.count_query} />
                                )}
                                {metric.query.kind === 'ExperimentFunnelsQuery' && (
                                    <MetricDisplayFunnels query={metric.query.funnels_query} />
                                )}
                            </div>
                        )
                    })()}
                </div>
            )}
        </LemonModal>
    )
}
