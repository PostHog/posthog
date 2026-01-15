import { useActions, useValues } from 'kea'

import { LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { FEATURE_FLAGS } from 'lib/constants'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import type { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import { ExperimentForm } from '~/scenes/experiments/ExperimentForm'
import { LegacyExperimentInfo } from '~/scenes/experiments/legacy/LegacyExperimentInfo'
import { ActivityScope, ProgressStatus } from '~/types'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { ExperimentMetricModal } from '../Metrics/ExperimentMetricModal'
import { LegacyMetricModal } from '../Metrics/LegacyMetricModal'
import { LegacyMetricSourceModal } from '../Metrics/LegacyMetricSourceModal'
import { LegacySharedMetricModal } from '../Metrics/LegacySharedMetricModal'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { experimentMetricModalLogic } from '../Metrics/experimentMetricModalLogic'
import { sharedMetricModalLogic } from '../Metrics/sharedMetricModalLogic'
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
import { SummarizeExperimentButton } from '../components/SummarizeExperimentButton'
import { experimentLogic } from '../experimentLogic'
import type { ExperimentSceneLogicProps } from '../experimentSceneLogic'
import { experimentSceneLogic } from '../experimentSceneLogic'
import { getExperimentStatus } from '../experimentsLogic'
import { isLegacyExperiment, isLegacyExperimentQuery } from '../utils'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { ExperimentFeedbackTab } from './ExperimentFeedbackTab'
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
        usesNewQueryRunner,
        featureFlags,
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

    const isAiSummaryEnabled =
        featureFlags[FEATURE_FLAGS.EXPERIMENT_AI_SUMMARY] === 'test' &&
        usesNewQueryRunner &&
        hasMinimumExposureForResults

    return (
        <>
            {isAiSummaryEnabled && (
                <div className="mt-1 mb-4 flex justify-start">
                    <SummarizeExperimentButton />
                </div>
            )}
            {usesNewQueryRunner && (
                <div className="w-full mb-4">
                    <Exposures />
                </div>
            )}

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

export function ExperimentView({ tabId }: Pick<ExperimentSceneLogicProps, 'tabId'>): JSX.Element {
    const { experimentLoading, experimentId, experiment, usesNewQueryRunner, isExperimentDraft, exposureCriteria } =
        useValues(experimentLogic)
    const { setExperiment, updateExperimentMetrics, addSharedMetricsToExperiment, removeSharedMetricFromExperiment } =
        useActions(experimentLogic)

    if (!tabId) {
        throw new Error('<ExperimentView /> must receive a tabId prop')
    }

    const { activeTabKey } = useValues(experimentSceneLogic({ tabId }))
    const { setActiveTabKey } = useActions(experimentSceneLogic({ tabId }))

    const { closeExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { closeSharedMetricModal } = useActions(sharedMetricModalLogic)

    /**
     * We show the create form if the experiment is draft + has no primary metrics. Otherwise,
     * we show the experiment view.
     */
    const allPrimaryMetrics = [
        ...(experiment.metrics || []),
        ...(experiment.saved_metrics || []).filter((sm) => sm.metadata.type === 'primary'),
    ]

    if (
        !experimentLoading &&
        getExperimentStatus(experiment) === ProgressStatus.Draft &&
        experiment.type === 'product' &&
        allPrimaryMetrics.length === 0
    ) {
        return <ExperimentForm draftExperiment={experiment} tabId={tabId} />
    }

    return (
        <SceneContent>
            <PageHeaderCustom />
            {experimentLoading ? (
                <LoadingState />
            ) : (
                <>
                    {usesNewQueryRunner ? <Info tabId={tabId} /> : <LegacyExperimentInfo />}
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
                            ...(!isExperimentDraft
                                ? [
                                      {
                                          key: 'code',
                                          label: 'Code',
                                          content: <CodeTab />,
                                      },
                                  ]
                                : []),
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
                            ...(experiment.feature_flag
                                ? [
                                      {
                                          key: 'feedback',
                                          label: (
                                              <div className="flex flex-row">
                                                  <div>User feedback</div>
                                                  <LemonTag className="ml-2 float-right uppercase" type="primary">
                                                      New
                                                  </LemonTag>
                                              </div>
                                          ),
                                          content: <ExperimentFeedbackTab experiment={experiment} />,
                                      },
                                  ]
                                : []),
                        ]}
                    />

                    {usesNewQueryRunner ? (
                        <>
                            <MetricSourceModal />
                            <ExperimentMetricModal
                                experiment={experiment}
                                exposureCriteria={exposureCriteria}
                                onSave={(metric, context) => {
                                    const metrics = experiment[context.field]
                                    const isNew = !metrics.some(({ uuid }) => uuid === metric.uuid)

                                    setExperiment({
                                        [context.field]: isNew
                                            ? [...metrics, metric]
                                            : metrics.map((m) => (m.uuid === metric.uuid ? metric : m)),
                                    })

                                    updateExperimentMetrics()
                                    closeExperimentMetricModal()
                                }}
                                onDelete={(metric, context) => {
                                    if (!metric.uuid) {
                                        return
                                    }

                                    setExperiment({
                                        [context.field]: experiment[context.field].filter(
                                            (m) => m.uuid !== metric.uuid
                                        ),
                                    })

                                    updateExperimentMetrics()
                                    closeExperimentMetricModal()
                                }}
                            />
                            <SharedMetricModal
                                experiment={experiment}
                                onSave={(metrics, context) => {
                                    addSharedMetricsToExperiment(
                                        metrics.map(({ id }) => id),
                                        { type: context.type }
                                    )
                                    closeSharedMetricModal()
                                }}
                                onDelete={(metric) => {
                                    removeSharedMetricFromExperiment(metric.id)
                                    closeSharedMetricModal()
                                }}
                            />
                            <ExposureCriteriaModal />
                            <RunningTimeCalculatorModal />
                        </>
                    ) : (
                        <>
                            <LegacyMetricSourceModal isSecondary={true} />
                            <LegacyMetricSourceModal isSecondary={false} />
                            <LegacySharedMetricModal isSecondary={true} />
                            <LegacySharedMetricModal isSecondary={false} />
                            <LegacyMetricModal isSecondary={true} />
                            <LegacyMetricModal isSecondary={false} />
                        </>
                    )}

                    <DistributionModal />
                    <ReleaseConditionsModal />

                    <StopExperimentModal />
                    <EditConclusionModal />

                    <VariantDeltaTimeseries />
                </>
            )}
        </SceneContent>
    )
}
