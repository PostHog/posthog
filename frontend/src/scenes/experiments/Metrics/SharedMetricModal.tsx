import { LemonBanner, LemonButton, LemonModal, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { MetricDisplayFunnels, MetricDisplayTrends } from '../ExperimentView/Goal'
import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'

export function SharedMetricModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const { sharedMetrics, isPrimarySharedMetricModalOpen, isSecondarySharedMetricModalOpen, editingSharedMetricId } =
        useValues(experimentLogic({ experimentId }))
    const {
        closePrimarySharedMetricModal,
        closeSecondarySharedMetricModal,
        addSharedMetricToExperiment,
        removeSharedMetricFromExperiment,
        loadExperiment,
    } = useActions(experimentLogic({ experimentId }))

    const [selectedMetricId, setSelectedMetricId] = useState<SharedMetric['id'] | null>(null)
    const [mode, setMode] = useState<'create' | 'edit'>('create')

    useEffect(() => {
        if (editingSharedMetricId) {
            setSelectedMetricId(editingSharedMetricId)
            setMode('edit')
        }
    }, [editingSharedMetricId])

    if (!sharedMetrics) {
        return <></>
    }

    const isOpen = isSecondary ? isSecondarySharedMetricModalOpen : isPrimarySharedMetricModalOpen
    const closeModal = (): void => {
        // :KLUDGE: Removes any local changes and resets the experiment to the server state
        loadExperiment()
        isSecondary ? closeSecondarySharedMetricModal() : closePrimarySharedMetricModal()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            width={500}
            title={mode === 'create' ? 'Select a shared metric' : 'Shared metric'}
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {editingSharedMetricId && (
                            <LemonButton
                                status="danger"
                                onClick={() => {
                                    removeSharedMetricFromExperiment(editingSharedMetricId)
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
                                        addSharedMetricToExperiment(selectedMetricId, {
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
                    {sharedMetrics.length > 0 ? (
                        <LemonSelect
                            options={sharedMetrics.map((metric: SharedMetric) => ({
                                label: metric.name,
                                value: metric.id,
                            }))}
                            placeholder="Select a shared metric"
                            loading={false}
                            value={selectedMetricId}
                            onSelect={(value) => {
                                setSelectedMetricId(value)
                            }}
                        />
                    ) : (
                        <LemonBanner
                            className="w-full"
                            type="info"
                            action={{
                                children: 'New shared metric',
                                to: urls.experimentsSharedMetric('new'),
                            }}
                        >
                            You don't have any shared metrics yet. Shared metrics let you create reusable metrics that
                            you can quickly add to any experiment.
                        </LemonBanner>
                    )}
                </div>
            )}

            {selectedMetricId && (
                <div>
                    {(() => {
                        const metric = sharedMetrics.find((m: SharedMetric) => m.id === selectedMetricId)
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
                                        to={urls.experimentsSharedMetric(metric.id)}
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
