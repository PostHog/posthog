import { LemonBanner, LemonButton, LemonModal, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
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
        addSharedMetricsToExperiment,
        removeSharedMetricFromExperiment,
    } = useActions(experimentLogic({ experimentId }))

    const [selectedMetricIds, setSelectedMetricIds] = useState<SharedMetric['id'][]>([])
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
    const closeModal = isSecondary ? closeSecondarySharedMetricModal : closePrimarySharedMetricModal

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            width={500}
            title={mode === 'create' ? 'Select one or more shared metrics' : 'Shared metric'}
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {editingSharedMetricId && (
                            <LemonButton
                                status="danger"
                                onClick={() => removeSharedMetricFromExperiment(editingSharedMetricId)}
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
                                    addSharedMetricsToExperiment(selectedMetricIds, {
                                        type: isSecondary ? 'secondary' : 'primary',
                                    })
                                }}
                                type="primary"
                                disabledReason={
                                    selectedMetricIds.length === 0 ? 'Please select at least one metric' : undefined
                                }
                            >
                                {selectedMetricIds.length < 2 ? 'Add metric' : 'Add metrics'}
                            </LemonButton>
                        )}
                    </div>
                </div>
            }
        >
            {mode === 'create' && (
                <div className="space-y-2">
                    {sharedMetrics.length > 0 ? (
                        <LemonTable
                            dataSource={sharedMetrics}
                            columns={[
                                {
                                    title: '',
                                    key: 'checkbox',
                                    render: (_, metric: SharedMetric) => (
                                        <input
                                            type="checkbox"
                                            checked={selectedMetricIds.includes(metric.id)}
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    setSelectedMetricIds([...selectedMetricIds, metric.id])
                                                } else {
                                                    setSelectedMetricIds(
                                                        selectedMetricIds.filter((id) => id !== metric.id)
                                                    )
                                                }
                                            }}
                                        />
                                    ),
                                },
                                {
                                    title: 'Name',
                                    dataIndex: 'name',
                                    key: 'name',
                                },
                                {
                                    title: 'Description',
                                    dataIndex: 'description',
                                    key: 'description',
                                },
                                {
                                    title: 'Type',
                                    key: 'type',
                                    render: (_, metric: SharedMetric) =>
                                        metric.query.kind.replace('Experiment', '').replace('Query', ''),
                                },
                            ]}
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
