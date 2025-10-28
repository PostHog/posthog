import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonButton, LemonDialog, LemonDivider, LemonModal, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { VariantTag } from '../../ExperimentView/components'
import { experimentTimeseriesLogic } from '../../experimentTimeseriesLogic'
import { MetricTitle } from '../shared/MetricTitle'
import { ExperimentVariantResult } from '../shared/utils'
import { ElapsedTime } from './ElapsedTime'
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
    const { chartData, progressMessage, hasTimeseriesData, timeseriesLoading, isRecalculating, timeseries } =
        useValues(logic)
    const { recalculateTimeseries, loadTimeseries } = useActions(logic)

    const processedChartData = useMemo(() => {
        return chartData(variantResult.key)
    }, [chartData, variantResult.key])

    const isStaleExperiment =
        !experiment.start_date || experiment.end_date
            ? false
            : dayjs(experiment.start_date).isBefore(dayjs().subtract(90, 'days'))

    const handleRecalculate = (): void => {
        LemonDialog.open({
            title: 'Recalculate timeseries data',
            content: (
                <div>
                    <p>
                        All existing timeseries data will be deleted and recalculated from scratch. This could take a
                        long time for large datasets.
                    </p>
                </div>
            ),
            primaryButton: {
                children: 'Recalculate',
                type: 'primary',
                onClick: () => recalculateTimeseries({ metric }),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

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
                ) : (
                    <div>
                        {isStaleExperiment && !isRecalculating && (
                            <div className="mb-2">
                                <LemonBanner type="warning">
                                    <div className="flex items-center justify-between">
                                        <div className="flex-1">
                                            <div className="text-sm">
                                                This experiment has been running for more than 90 days. Automatic
                                                timeseries updates are disabled. You can still manually recalculate the
                                                data.
                                            </div>
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={handleRecalculate}
                                            className="ml-4"
                                        >
                                            Recalculate
                                        </LemonButton>
                                    </div>
                                </LemonBanner>
                            </div>
                        )}
                        {isRecalculating && (
                            <div className="mb-4">
                                <LemonBanner type="info">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <Spinner className="text-sm" />
                                            <span>
                                                Recalculating •{' '}
                                                <ElapsedTime startTime={timeseries?.recalculation_created_at} /> elapsed
                                                •
                                            </span>
                                            <Link onClick={() => loadTimeseries({ metric })}>Refresh</Link>
                                        </div>
                                    </div>
                                </LemonBanner>
                            </div>
                        )}
                        <div className="flex justify-between items-center mt-2 mb-4">
                            <div className="text-xs text-muted">{progressMessage || ''}</div>
                            <More
                                overlay={
                                    <>
                                        <LemonButton onClick={handleRecalculate}>Recalculate</LemonButton>
                                    </>
                                }
                            />
                        </div>
                        {hasTimeseriesData ? (
                            processedChartData ? (
                                <VariantTimeseriesChart chartData={processedChartData} />
                            ) : (
                                <div className="p-10 text-center text-muted">
                                    No timeseries data available for this variant
                                </div>
                            )
                        ) : (
                            <div className="p-10 text-center text-muted -translate-y-6">
                                No timeseries data available
                            </div>
                        )}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
