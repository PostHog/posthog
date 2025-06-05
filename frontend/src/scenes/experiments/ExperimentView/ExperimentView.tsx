import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic, isLegacyExperimentResponseGeneric } from '../experimentLogic'
import { ExperimentMetricModal } from '../Metrics/ExperimentMetricModal'
import { LegacyMetricModal } from '../Metrics/LegacyMetricModal'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { MetricsView } from '../MetricsView/MetricsView'
import { VariantDeltaTimeseries } from '../MetricsView/VariantDeltaTimeseries'
import { RunningTimeCalculatorModal } from '../RunningTimeCalculator/RunningTimeCalculatorModal'
import {
    EditConclusionModal,
    ExploreButton,
    LoadingState,
    PageHeaderCustom,
    ResultsQuery,
    StopExperimentModal,
} from './components'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { ExperimentHeader } from './ExperimentHeader'
import { ExposureCriteriaModal } from './ExposureCriteria'
import { Info } from './Info'
import { LegacyExperimentHeader } from './LegacyExperimentHeader'
import { Overview } from './Overview'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { SummaryTable } from './SummaryTable'

const ResultsTab = (): JSX.Element => {
    const {
        experiment,
        metricResults,
        firstPrimaryMetric,
        primaryMetricsLengthWithSharedMetrics,
        metricResultsLoading,
        hasMinimumExposureForResults,
    } = useValues(experimentLogic)
    const hasSomeResults = metricResults?.some(
        (result) => result && isLegacyExperimentResponseGeneric(result) && result?.insight
    )

    const hasSinglePrimaryMetric = primaryMetricsLengthWithSharedMetrics === 1

    return (
        <>
            {!experiment.start_date && !metricResultsLoading && (
                <>
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} />
                    )}
                </>
            )}
            {/* Show overview if there's only a single primary metric */}
            {hasSinglePrimaryMetric && hasMinimumExposureForResults && (
                <div className="mb-4 mt-2">
                    <Overview />
                </div>
            )}
            <MetricsView isSecondary={false} />
            {/* Show detailed results if there's only a single primary metric */}
            {hasSomeResults && hasMinimumExposureForResults && hasSinglePrimaryMetric && firstPrimaryMetric && (
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
    return (
        <div className="deprecated-space-y-8 mt-2">
            <ReleaseConditionsTable />
            <DistributionTable />
        </div>
    )
}

export function ExperimentView(): JSX.Element {
    const { experimentLoading, experimentId, tabKey, usesNewQueryRunner } = useValues(experimentLogic)

    const { setTabKey } = useActions(experimentLogic)

    return (
        <>
            <PageHeaderCustom />
            <div className="deprecated-space-y-8 experiment-view">
                {experimentLoading ? (
                    <LoadingState />
                ) : (
                    <>
                        <Info />
                        {usesNewQueryRunner ? <ExperimentHeader /> : <LegacyExperimentHeader />}
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

                        {usesNewQueryRunner ? (
                            <>
                                <ExperimentMetricModal experimentId={experimentId} isSecondary={true} />
                                <ExperimentMetricModal experimentId={experimentId} isSecondary={false} />
                                <ExposureCriteriaModal />
                                <RunningTimeCalculatorModal />
                            </>
                        ) : (
                            <>
                                <LegacyMetricModal experimentId={experimentId} isSecondary={true} />
                                <LegacyMetricModal experimentId={experimentId} isSecondary={false} />
                            </>
                        )}

                        <SharedMetricModal experimentId={experimentId} isSecondary={true} />
                        <SharedMetricModal experimentId={experimentId} isSecondary={false} />

                        <DistributionModal experimentId={experimentId} />
                        <ReleaseConditionsModal experimentId={experimentId} />

                        <StopExperimentModal experimentId={experimentId} />
                        <EditConclusionModal experimentId={experimentId} />

                        <VariantDeltaTimeseries />
                    </>
                )}
            </div>
        </>
    )
}
