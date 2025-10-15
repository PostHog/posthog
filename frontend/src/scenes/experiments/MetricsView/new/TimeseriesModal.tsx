import { useValues } from 'kea'

import { LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { VariantTag } from '../../ExperimentView/components'
import { experimentTimeseriesLogic } from '../../experimentTimeseriesLogic'
import { MetricTitle } from '../shared/MetricTitle'
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
    const logic = experimentTimeseriesLogic({ experimentId: experiment.id, metric: isOpen ? metric : undefined })
    const { chartData, progressMessage, hasTimeseriesData, timeseriesLoading } = useValues(logic)

    const processedChartData = chartData(variantResult.key)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title={
                <div className="flex items-center gap-2 text-sm">
                    <div className="flex items-center">
                        <span>Time series</span>
                    </div>
                    <LemonDivider vertical className="h-4 self-stretch" />
                    <div className="flex items-center">
                        <MetricTitle metric={metric} />
                    </div>
                    <LemonDivider vertical className="h-4 self-stretch" />
                    <div className="flex items-center">
                        <VariantTag experimentId={experiment.id} variantKey={variantResult.key} />
                    </div>
                </div>
            }
            footer={
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <div>
                {timeseriesLoading ? (
                    <div
                        className="flex items-center justify-center gap-2 text-[14px] font-normal"
                        style={{ height: '200px' }}
                    >
                        <Spinner className="text-lg" />
                        <span>Loading timeseries&hellip;</span>
                    </div>
                ) : hasTimeseriesData ? (
                    <div>
                        {progressMessage && <div className="text-xs text-muted mt-2 mb-4">{progressMessage}</div>}
                        {processedChartData ? (
                            <VariantTimeseriesChart chartData={processedChartData} />
                        ) : (
                            <div className="p-10 text-center text-muted">
                                No timeseries data available for this variant
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
