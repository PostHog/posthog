import { useValues } from 'kea'
import { useState } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import type { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { ExperimentMetricModal } from '../Metrics/ExperimentMetricModal'
import { LegacyMetricModal } from '../Metrics/LegacyMetricModal'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { MetricsViewLegacy } from '../MetricsView/legacy/MetricsViewLegacy'
import { VariantDeltaTimeseries } from '../MetricsView/legacy/VariantDeltaTimeseries'
import { Metrics } from '../MetricsView/new/Metrics'
import { RunningTimeCalculatorModal } from '../RunningTimeCalculator/RunningTimeCalculatorModal'
import {
    ExploreAsInsightButton,
    ResultsBreakdown,
    ResultsBreakdownSkeleton,
    ResultsInsightInfoBanner,
    ResultsQuery,
} from '../components/ResultsBreakdown'
import { experimentLogic } from '../experimentLogic'
import { isLegacyExperiment, isLegacyExperimentQuery } from '../utils'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { ExperimentHeader } from './ExperimentHeader'
import { ExposureCriteriaModal } from './ExposureCriteria'
import { Exposures } from './Exposures'
import { Info } from './Info'
import { LegacyExperimentHeader } from './LegacyExperimentHeader'
import { Overview } from './Overview'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { SummaryTable } from './SummaryTable'
import {
    EditConclusionModal,
    LegacyExploreButton,
    LegacyResultsQuery,
    LoadingState,
    PageHeaderCustom,
    StopExperimentModal,
} from './components'

const MetricsTab = (): JSX.Element => {
    const {
        experiment,
        legacyPrimaryMetricsResults,
        firstPrimaryMetric,
        primaryMetricsLengthWithSharedMetrics,
        hasMinimumExposureForResults,
    } = useValues(experimentLogic)
    /**
     * we still use the legacy metric results here. Results on the new format are loaded
     * in the primaryMetricsResults state key. We'll eventually move into using the new state.
     */
    const hasSomeResults = legacyPrimaryMetricsResults?.some((result) => result?.insight)

    const hasSinglePrimaryMetric = primaryMetricsLengthWithSharedMetrics === 1

    const firstPrimaryMetricResult = legacyPrimaryMetricsResults?.[0]

    const hasLegacyResults = legacyPrimaryMetricsResults.some((result) => result != null)

    /**
     * Show a detailed results if:
     * - there's a single primary metric
     * - if the metric has insight results
     * - if we have the minimum number of exposures
     * - if it's the first primary metric (?)
     *
     * this is only for legacy experiments.
     */
    const showResultDetails =
        hasSomeResults &&
        hasMinimumExposureForResults &&
        hasSinglePrimaryMetric &&
        firstPrimaryMetric &&
        firstPrimaryMetricResult

    return (
        <>
            <div className="w-full mb-4">
                <Exposures />
            </div>

            {/* Show overview if there's only a single primary metric */}
            {hasSinglePrimaryMetric && hasMinimumExposureForResults && (
                <div className="mb-4 mt-2">
                    <Overview metricUuid={firstPrimaryMetric?.uuid || ''} />
                </div>
            )}
            {/**
             *  check if we should render the legacy metrics view or the new one
             */}
            {isLegacyExperiment(experiment) || hasLegacyResults ? (
                <>
                    <MetricsViewLegacy isSecondary={false} />
                    {showResultDetails && (
                        <div>
                            <div className="pb-4">
                                <SummaryTable metric={firstPrimaryMetric} displayOrder={0} isSecondary={false} />
                            </div>
                            {isLegacyExperimentQuery(firstPrimaryMetricResult) ? (
                                <>
                                    <div className="flex justify-end">
                                        <LegacyExploreButton result={firstPrimaryMetricResult} size="xsmall" />
                                    </div>
                                    <div className="pb-4">
                                        <LegacyResultsQuery
                                            result={firstPrimaryMetricResult || null}
                                            showTable={true}
                                        />
                                    </div>
                                </>
                            ) : (
                                /**
                                 * altough we don't have a great typeguard here, we know that the result is a CachedExperimentQueryResponse
                                 * because we're only showing results for experiment queries (legacy check)
                                 */
                                <ResultsBreakdown
                                    result={firstPrimaryMetricResult as CachedExperimentQueryResponse}
                                    experiment={experiment}
                                    metricUuid={firstPrimaryMetric?.uuid || ''}
                                    isPrimary={true}
                                >
                                    {({
                                        query,
                                        breakdownResults,
                                        breakdownResultsLoading,
                                        exposureDifference,
                                        breakdownLastRefresh,
                                    }) => (
                                        <div>
                                            {breakdownResultsLoading && <ResultsBreakdownSkeleton />}
                                            {query && breakdownResults && (
                                                <div>
                                                    <div className="flex justify-end">
                                                        <ExploreAsInsightButton query={query} />
                                                    </div>
                                                    <ResultsInsightInfoBanner exposureDifference={exposureDifference} />
                                                    <div className="pb-4">
                                                        <ResultsQuery
                                                            query={query}
                                                            breakdownResults={breakdownResults}
                                                            breakdownLastRefresh={breakdownLastRefresh}
                                                        />
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </ResultsBreakdown>
                            )}
                        </div>
                    )}
                    <MetricsViewLegacy isSecondary={true} />
                </>
            ) : (
                <>
                    <Metrics isSecondary={false} />
                    <Metrics isSecondary={true} />
                </>
            )}
        </>
    )
}
const CodeTab = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)

    return (
        <>
            {experiment.type === 'web' ? (
                <WebExperimentImplementationDetails experiment={experiment} />
            ) : (
                <ExperimentImplementationDetails experiment={experiment} />
            )}
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
    const { experimentLoading, experimentId, usesNewQueryRunner } = useValues(experimentLogic)

    const [activeTabKey, setActiveTabKey] = useState<string>('metrics')

    return (
        <SceneContent>
            <PageHeaderCustom />
            {experimentLoading ? (
                <LoadingState />
            ) : (
                <>
                    <Info />
                    {usesNewQueryRunner ? <ExperimentHeader /> : <LegacyExperimentHeader />}
                    <LemonTabs
                        activeKey={activeTabKey}
                        onChange={(key) => setActiveTabKey(key)}
                        sceneInset
                        tabs={[
                            {
                                key: 'metrics',
                                label: 'Metrics',
                                content: <MetricsTab />,
                            },
                            {
                                key: 'code',
                                label: 'Code',
                                content: <CodeTab />,
                            },
                            {
                                key: 'variants',
                                label: 'Variants',
                                content: <VariantsTab />,
                            },
                            {
                                key: 'history',
                                label: 'History',
                                content: <ActivityLog scope={ActivityScope.EXPERIMENT} id={experimentId} />,
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
        </SceneContent>
    )
}
