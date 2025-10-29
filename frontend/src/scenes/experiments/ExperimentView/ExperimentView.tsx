import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import type { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
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
import { CreateExperiment } from '../create/CreateExperiment'
import { experimentLogic } from '../experimentLogic'
import { getExperimentStatus } from '../experimentsLogic'
import { isLegacyExperiment, isLegacyExperimentQuery, removeMetricFromOrderingArray } from '../utils'
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
        usesNewQueryRunner,
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

export function ExperimentView(): JSX.Element {
    const { experimentLoading, experimentId, experiment, usesNewQueryRunner, isExperimentDraft, exposureCriteria } =
        useValues(experimentLogic)
    const { setExperiment, updateExperimentMetrics, addSharedMetricsToExperiment, removeSharedMetricFromExperiment } =
        useActions(experimentLogic)

    const { closeExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { closeSharedMetricModal } = useActions(sharedMetricModalLogic)

    const [activeTabKey, setActiveTabKey] = useState<string>('metrics')

    /**
     * this is temporary, for testing purposes only.
     * this has to be migrated into a scene with a proper path, and paramsToProps
     * so it works seamlesly with the toolbar and tab bar navigation.
     *
     * We show the create form if the experiment is draft + has no metrics. Otherwise,
     * we show the experiment view.
     */
    const isUnifiedCreateFormEnabled = useFeatureFlag('EXPERIMENTS_UNIFIED_CREATE_FORM', 'test')
    const allPrimaryMetrics = [...(experiment.metrics || []), ...(experiment.saved_metrics || [])]

    if (
        !experimentLoading &&
        isUnifiedCreateFormEnabled &&
        getExperimentStatus(experiment) === ProgressStatus.Draft &&
        allPrimaryMetrics.length === 0
    ) {
        return <CreateExperiment draftExperiment={experiment} />
    }

    return (
        <SceneContent>
            <PageHeaderCustom />
            {experimentLoading ? (
                <LoadingState />
            ) : (
                <>
                    {usesNewQueryRunner ? <Info /> : <LegacyExperimentInfo />}
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
                                        ...(isNew && {
                                            [context.orderingField]: [
                                                ...(experiment[context.orderingField] ?? []),
                                                metric.uuid,
                                            ],
                                        }),
                                    })

                                    updateExperimentMetrics()
                                    closeExperimentMetricModal()
                                }}
                                onDelete={(metric, context) => {
                                    //bail if the metric has no uuid
                                    if (!metric.uuid) {
                                        return
                                    }

                                    setExperiment({
                                        [context.field]: experiment[context.field].filter(
                                            (m) => m.uuid !== metric.uuid
                                        ),
                                        [context.orderingField]: removeMetricFromOrderingArray(
                                            experiment,
                                            metric.uuid,
                                            context.type === 'secondary'
                                        ),
                                    })

                                    updateExperimentMetrics()
                                    closeExperimentMetricModal()
                                }}
                            />
                            <SharedMetricModal
                                experiment={experiment}
                                onSave={(metrics, context) => {
                                    const existingOrderingArray = experiment[context.orderingField] ?? []
                                    const newMetricUuids = metrics
                                        .map((metric) => metric.query.uuid)
                                        .filter((uuid) => !existingOrderingArray.includes(uuid))
                                    const newOrderingArray = [...existingOrderingArray, ...newMetricUuids]

                                    setExperiment({
                                        [context.orderingField]: newOrderingArray,
                                    })

                                    addSharedMetricsToExperiment(
                                        metrics.map(({ id }) => id),
                                        { type: context.type }
                                    )
                                    closeSharedMetricModal()
                                }}
                                onDelete={(metric, context) => {
                                    const newOrderingArray = removeMetricFromOrderingArray(
                                        experiment,
                                        metric.query.uuid,
                                        context.type === 'secondary'
                                    )

                                    setExperiment({
                                        [context.orderingField]: newOrderingArray,
                                    })

                                    removeSharedMetricFromExperiment(metric.id)
                                    closeSharedMetricModal()
                                }}
                            />
                            <ExposureCriteriaModal />
                            <RunningTimeCalculatorModal />
                        </>
                    ) : (
                        <>
                            <LegacyMetricSourceModal experimentId={experimentId} isSecondary={true} />
                            <LegacyMetricSourceModal experimentId={experimentId} isSecondary={false} />
                            <LegacySharedMetricModal experimentId={experimentId} isSecondary={true} />
                            <LegacySharedMetricModal experimentId={experimentId} isSecondary={false} />
                            <LegacyMetricModal experimentId={experimentId} isSecondary={true} />
                            <LegacyMetricModal experimentId={experimentId} isSecondary={false} />
                        </>
                    )}

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
