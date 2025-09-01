import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { P, match } from 'ts-pattern'

import { FunnelLayout } from 'lib/constants'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { performQuery } from '~/queries/query'
import type {
    ExperimentEventExposureConfig,
    ExperimentMetric,
    FunnelsQuery,
    InsightVizNode,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind, isExperimentFunnelMetric } from '~/queries/schema/schema-general'
import {
    addExposureToMetric,
    compose,
    getExperimentDateRange,
    getExposureConfigEventsNode,
    getInsight,
    getQuery,
} from '~/scenes/experiments/metricQueryUtils'
import type { Experiment, FunnelStep } from '~/types'
import {
    BreakdownAttributionType,
    FunnelConversionWindowTimeUnit,
    FunnelStepReference,
    FunnelVizType,
    StepOrderValue,
} from '~/types'

import type { resultsBreakdownLogicType } from './resultsBreakdownLogicType'

const filterFunnelSteps = (steps: FunnelStep[], variants: string[]): FunnelStep[] =>
    steps.filter((step) =>
        match(step.breakdown_value)
            .with(undefined, () => false)
            .with(P.array(P.string), (values) => values.some((value) => variants.includes(value)))
            .otherwise(() => variants.includes(step.breakdown_value as string))
    )

export type ResultBreakdownLogicProps = {
    experiment: Experiment
    metric?: ExperimentMetric
    metricUuid: string
    isPrimary: boolean
}

/**
 * This logic only works with the new query runner.
 * Legacy Funnels and Trends engine are resolved backend side.
 */
export const resultsBreakdownLogic = kea<resultsBreakdownLogicType>([
    props({
        experiment: {} as Experiment,
        metric: {} as ExperimentMetric,
    } as ResultBreakdownLogicProps),

    key((props) => `${props.experiment.id}-${props.metricUuid}-${props.isPrimary ? 'primary' : 'secondary'}`),

    path((key) => ['scenes', 'experiment', 'experimentResultBreakdownLogic', key]),

    connect((props: ResultBreakdownLogicProps) => ({
        actions: [experimentLogic({ experimentId: props.experiment.id }), ['refreshExperimentResults']],
    })),

    actions({
        loadBreakdownResults: (refresh?: boolean) => ({ refresh }),
        setBreakdownLastRefresh: (lastRefresh: string | null) => ({ lastRefresh }),
    }),

    selectors({
        query: [
            () => [(_, props) => props],
            ({ experiment, metric }: ResultBreakdownLogicProps) => {
                if (!metric) {
                    return null
                }

                /**
                 * we create the exposure node. For this case, we need
                 * need to use the experiment's exposure config
                 */
                const exposureEventNode = getExposureConfigEventsNode(
                    experiment.exposure_criteria?.exposure_config as ExperimentEventExposureConfig,
                    {
                        featureFlagKey: experiment.feature_flag_key,
                        featureFlagVariants: experiment.parameters.feature_flag_variants,
                    }
                )

                /**
                 * we create the query builder with all the options.
                 */
                const queryBuilder = compose<
                    ExperimentMetric,
                    ExperimentMetric,
                    FunnelsQuery | TrendsQuery | undefined,
                    InsightVizNode | undefined
                >(
                    addExposureToMetric(exposureEventNode),
                    getQuery({
                        filterTestAccounts: !!experiment.exposure_criteria?.filterTestAccounts,
                        dateRange: getExperimentDateRange(experiment),
                        breakdownFilter: {
                            breakdown:
                                exposureEventNode.event === '$feature_flag_called'
                                    ? '$feature_flag_response'
                                    : `$feature/${experiment.feature_flag_key}`,
                            breakdown_type: 'event',
                        },
                        funnelsFilter: {
                            layout: FunnelLayout.vertical,
                            /* We want to break down results by the flag value from the _first_ step
                            which is the expsoure criteria */
                            breakdownAttributionType: BreakdownAttributionType.Step,
                            breakdownAttributionValue: 0,
                            funnelOrderType:
                                (isExperimentFunnelMetric(metric) && metric.funnel_order_type) ||
                                StepOrderValue.ORDERED,
                            funnelStepReference: FunnelStepReference.total,
                            funnelVizType: FunnelVizType.Steps,
                            funnelWindowInterval: 14,
                            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                        },
                    }),
                    getInsight({
                        showTable: true,
                        showLastComputation: true,
                        showLastComputationRefresh: false,
                    })
                )

                /**
                 * take the metric and the experiment and create a new Funnel or Trends query.
                 * we need the experiment for exposure configuration.
                 */
                return queryBuilder(metric) || null
            },
        ],
    }),

    reducers({
        breakdownLastRefresh: [
            null as string | null,
            {
                setBreakdownLastRefresh: (_, { lastRefresh }) => lastRefresh,
                loadBreakdownResults: () => null, // Clear when loading starts
            },
        ],
    }),

    loaders(({ props, values, actions }) => ({
        breakdownResults: [
            null as FunnelStep[] | FunnelStep[][] | null,
            {
                loadBreakdownResults: async ({ refresh }): Promise<FunnelStep[] | FunnelStep[][]> => {
                    try {
                        const { experiment } = props
                        const query = values.query

                        if (!query) {
                            throw new Error('No query returned from queryBuilder')
                        }

                        if (query.source.kind === NodeKind.TrendsQuery) {
                            return []
                        }

                        /**
                         * perform the query - use cache on normal load, force refresh when explicitly requested
                         */
                        const response = (await performQuery(query, undefined, refresh ? 'force_async' : 'async')) as {
                            results: FunnelStep[] | FunnelStep[][]
                            last_refresh?: string
                        }

                        if (!response?.results) {
                            throw new Error('No results returned from query')
                        }

                        // Capture the last_refresh timestamp for use in cachedInsight
                        if (response.last_refresh) {
                            actions.setBreakdownLastRefresh(response.last_refresh)
                        }

                        let results = response.results

                        /**
                         * we need to filter the results to remove any non-variant breakdown
                         */
                        const variants = experiment.parameters.feature_flag_variants.map(({ key }) => key)

                        results = match(results)
                            /**
                             * filter for FunnelSteps[][]. In this case, we get an array for each breakdown group,
                             * each with an array of steps. We need to filter for each group and remove any empty arrays.
                             */
                            .with(P.array(P.array({ breakdown_value: P.any })), (nestedSteps) =>
                                nestedSteps
                                    .map((stepGroup) => filterFunnelSteps(stepGroup, variants))
                                    .filter((steps) => steps.length > 0)
                            )
                            /**
                             * filter for FunnelSteps[]. In this case, we just get an array of steps
                             */
                            .with(P.array({ breakdown_value: P.any }), (flatSteps) =>
                                filterFunnelSteps(flatSteps, variants)
                            )
                            .otherwise(() => [])

                        return results
                    } catch (error) {
                        throw new Error(
                            error instanceof Error
                                ? `Failed to load experiment results: ${error.message}`
                                : 'Failed to load experiment results'
                        )
                    }
                },
            },
        ],
    })),

    listeners(({ actions, props }) => ({
        refreshExperimentResults: () => {
            const { metric, experiment } = props

            // bail if no valid props
            if (!experiment || !metric) {
                return
            }

            // bail if unsupported metric type
            if (metric.kind !== NodeKind.ExperimentMetric || metric.metric_type !== ExperimentMetricType.FUNNEL) {
                return
            }

            // Refresh the breakdown results when experiment results are refreshed
            actions.loadBreakdownResults(true)
        },
    })),

    afterMount(({ actions, props }) => {
        const { metric, experiment } = props

        // bail if no valid props
        if (!experiment || !metric) {
            return
        }

        // bail if unsupported metric type
        if (metric.kind !== NodeKind.ExperimentMetric || metric.metric_type !== ExperimentMetricType.FUNNEL) {
            return
        }

        actions.loadBreakdownResults()
    }),
])
