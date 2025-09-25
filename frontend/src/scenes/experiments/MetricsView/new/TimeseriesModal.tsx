import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { experimentTimeseriesLogic } from '../../experimentTimeseriesLogic'
import { ExperimentVariantResult } from '../shared/utils'
import { VariantTimeseriesChart } from './VariantTimeseriesChart'

interface TimeseriesModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric
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
    const { chartData, progressMessage, hasTimeseriesData } = useValues(logic)

    useEffect(() => {
        if (isOpen && metric.uuid && metric.fingerprint) {
            loadTimeseries({ metric })
        }
        return () => {
            clearTimeseries()
        }
    }, [isOpen, metric])

    const processedChartData = chartData(variantResult.key)
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
            <div>
                {hasTimeseriesData ? (
                    <div>
                        {progressMessage && <div className="text-xs text-muted mt-2 mb-4">{progressMessage}</div>}
                        {processedChartData ? (
                            <VariantTimeseriesChart chartData={processedChartData} />
                        ) : (
                            <div style={{ padding: '40px', textAlign: 'center', color: '#666' }}>
                                No timeseries data available for {variantName}
                            </div>
                        )}
                    </div>
                ) : (
                    <div style={{ padding: '40px', textAlign: 'center', color: '#666' }}>
                        No timeseries data available
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
