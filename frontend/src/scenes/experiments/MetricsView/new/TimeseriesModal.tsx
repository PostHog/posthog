import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { experimentTimeseriesLogic } from '../../experimentTimeseriesLogic'
import { ExperimentVariantResult } from '../shared/utils'
import { VariantTimeseriesChart } from './VariantTimeseriesChart'

interface TimeseriesModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    variantResult: ExperimentVariantResult
    experiment: Experiment
}

export function TimeseriesModal({
    isOpen,
    onClose,
    metric,
    variantResult,
    experiment,
}: TimeseriesModalProps): JSX.Element {
    const logic = experimentTimeseriesLogic({ experimentId: experiment.id })
    const { loadTimeseries, clearTimeseries } = useActions(logic)
    const { timeseries, chartData } = useValues(logic)

    useEffect(() => {
        if (isOpen && metric.uuid) {
            loadTimeseries(metric.uuid)
        }
        return () => {
            clearTimeseries()
        }
    }, [isOpen, metric.uuid, clearTimeseries, loadTimeseries])

    // TEMPORARY: Filter data to end on 2025-06-05 for screenshot
    const processedChartData = chartData(variantResult.key, '2025-06-05')
    const variantName =
        experiment.parameters?.feature_flag_variants?.find((v) => v.key === variantResult.key)?.name ||
        variantResult.key

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title={`${variantName} Performance over time - ${metric.name || 'Untitled metric'}`}
            footer={
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <div style={{ padding: '16px' }}>
                {timeseries ? (
                    <div>
                        {timeseries.status === 'completed' && timeseries.timeseries ? (
                            <>
                                {processedChartData ? (
                                    <VariantTimeseriesChart chartData={processedChartData} />
                                ) : (
                                    <div
                                        style={{
                                            padding: '40px',
                                            textAlign: 'center',
                                            color: '#666',
                                        }}
                                    >
                                        No timeseries data available for {variantName}
                                    </div>
                                )}
                            </>
                        ) : timeseries.status === 'failed' ? (
                            <div style={{ color: 'red', marginTop: '10px' }}>
                                Error: {timeseries.error_message || 'Failed to compute timeseries'}
                            </div>
                        ) : (
                            <div style={{ marginTop: '10px' }}>Timeseries computation is pending...</div>
                        )}
                    </div>
                ) : (
                    <div>Loading timeseries data...</div>
                )}
            </div>
        </LemonModal>
    )
}
