import { IconCalculator } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { ExperimentMetricModal } from '../Metrics/ExperimentMetricModal'
import { LegacyMetricModal } from '../Metrics/LegacyMetricModal'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { MetricsView } from '../MetricsView/MetricsView'
import { VariantDeltaTimeseries } from '../MetricsView/VariantDeltaTimeseries'
import { RunningTimeCalculatorModal } from '../RunningTimeCalculator/RunningTimeCalculatorModal'
import { ExploreButton, LoadingState, PageHeaderCustom, ResultsQuery } from './components'
import { DataCollection } from './DataCollection'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { ExposureCriteria } from './ExposureCriteria'
import { Exposures } from './Exposures'
import { Info } from './Info'
import { Overview } from './Overview'
import { PreLaunchChecklist } from './PreLaunchChecklist'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { SummaryTable } from './SummaryTable'

const ResultsTab = (): JSX.Element => {
    const {
        experiment,
        metricResults,
        firstPrimaryMetric,
        primaryMetricsLengthWithSharedMetrics,
        metricResultsLoading,
    } = useValues(experimentLogic)
    const hasSomeResults = metricResults?.some((result) => result?.insight)

    const hasSinglePrimaryMetric = primaryMetricsLengthWithSharedMetrics === 1

    return (
        <>
            {!hasSomeResults && !metricResultsLoading && (
                <>
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} />
                    )}
                </>
            )}
            {/* Show overview if there's only a single primary metric */}
            {hasSinglePrimaryMetric && (
                <div className="mb-4 mt-2">
                    <Overview />
                </div>
            )}
            <MetricsView isSecondary={false} />
            {/* Show detailed results if there's only a single primary metric */}
            {hasSomeResults && hasSinglePrimaryMetric && firstPrimaryMetric && (
                <div>
                    <div className="pb-4">
                        <SummaryTable metric={firstPrimaryMetric} metricIndex={0} isSecondary={false} />
                    </div>
                    {/* TODO: Only show explore button results viz if the metric is a trends or funnels query. Not supported yet with new query runner */}
                    {metricResults?.[0] &&
                        (metricResults[0].kind === 'ExperimentTrendsQuery' ||
                            metricResults[0].kind === 'ExperimentFunnelsQuery') && (
                            <>
                                <div className="flex justify-end">
                                    <ExploreButton result={metricResults[0]} size="xsmall" />
                                </div>
                                <div className="pb-4">
                                    <ResultsQuery result={metricResults?.[0] || null} showTable={true} />
                                </div>
                            </>
                        )}
                </div>
            )}
            <MetricsView isSecondary={true} />
        </>
    )
}

const VariantsTab = (): JSX.Element => {
    const { shouldUseExperimentMetrics, isExperimentRunning } = useValues(experimentLogic)
    return (
        <div className="space-y-8 mt-2">
            {shouldUseExperimentMetrics && isExperimentRunning && <Exposures />}
            <ReleaseConditionsTable />
            <DistributionTable />
        </div>
    )
}

export function ExperimentView(): JSX.Element {
    const { experiment, experimentLoading, experimentId, tabKey, shouldUseExperimentMetrics } =
        useValues(experimentLogic)

    const { setTabKey, openCalculateRunningTimeModal } = useActions(experimentLogic)

    return (
        <>
            <PageHeaderCustom />
            <div className="space-y-8 experiment-view">
                {experimentLoading ? (
                    <LoadingState />
                ) : (
                    <>
                        <Info />
                        <div className="xl:flex">
                            {shouldUseExperimentMetrics ? (
                                <>
                                    <div className="w-1/2 mt-8 xl:mt-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <h2 className="font-semibold text-lg m-0">Data collection</h2>
                                            <LemonButton
                                                icon={<IconCalculator />}
                                                type="secondary"
                                                size="xsmall"
                                                onClick={openCalculateRunningTimeModal}
                                                tooltip="Calculate running time"
                                            />
                                        </div>
                                        <div>
                                            <span className="card-secondary">Sample size:</span>{' '}
                                            <span className="font-semibold">
                                                {humanFriendlyNumber(
                                                    experiment.parameters.recommended_sample_size || 0,
                                                    0
                                                )}{' '}
                                                persons
                                            </span>
                                        </div>
                                        <div>
                                            <span className="card-secondary">Running time:</span>{' '}
                                            <span className="font-semibold">
                                                {humanFriendlyNumber(
                                                    experiment.parameters.recommended_running_time || 0,
                                                    0
                                                )}
                                            </span>{' '}
                                            days
                                        </div>
                                        <div className="mt-4">
                                            <ExposureCriteria />
                                        </div>
                                    </div>
                                    <PreLaunchChecklist />
                                </>
                            ) : (
                                <div className="w-1/2 mt-8 xl:mt-0">
                                    <DataCollection />
                                </div>
                            )}
                        </div>
                        <LemonTabs
                            activeKey={tabKey}
                            onChange={(key) => setTabKey(key)}
                            tabs={[
                                {
                                    key: 'results',
                                    label: 'Results',
                                    content: <ResultsTab />,
                                },
                                {
                                    key: 'variants',
                                    label: 'Variants',
                                    content: <VariantsTab />,
                                },
                            ]}
                        />

                        <MetricSourceModal experimentId={experimentId} isSecondary={true} />
                        <MetricSourceModal experimentId={experimentId} isSecondary={false} />

                        {shouldUseExperimentMetrics ? (
                            <>
                                <ExperimentMetricModal experimentId={experimentId} isSecondary={true} />
                                <ExperimentMetricModal experimentId={experimentId} isSecondary={false} />
                            </>
                        ) : (
                            <>
                                <LegacyMetricModal experimentId={experimentId} isSecondary={true} />
                                <LegacyMetricModal experimentId={experimentId} isSecondary={false} />
                            </>
                        )}

                        <RunningTimeCalculatorModal />

                        <SharedMetricModal experimentId={experimentId} isSecondary={true} />
                        <SharedMetricModal experimentId={experimentId} isSecondary={false} />

                        <DistributionModal experimentId={experimentId} />
                        <ReleaseConditionsModal experimentId={experimentId} />

                        <VariantDeltaTimeseries />
                    </>
                )}
            </div>
        </>
    )
}
