import { actions, afterMount, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { FunnelLayout } from 'lib/constants'
import { match, P } from 'ts-pattern'

import { performQuery } from '~/queries/query'
import type {
    ExperimentEventExposureConfig,
    ExperimentMetric,
    FunnelsQuery,
    InsightVizNode,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { ExperimentMetricType, isExperimentFunnelMetric, NodeKind } from '~/queries/schema/schema-general'
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
    metricIndex: number
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

    key((props) => `${props.experiment.id}-${props.metricIndex}-${props.isPrimary ? 'primary' : 'secondary'}`),

    path((key) => ['scenes', 'experiment', 'experimentResultBreakdownLogic', key]),

    actions({
        loadBreakdownResults: true,
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

    loaders(({ props, values }) => ({
        breakdownResults: [
            null as FunnelStep[] | FunnelStep[][] | null,
            {
                loadBreakdownResults: async (): Promise<FunnelStep[] | FunnelStep[][]> => {
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
                         * perform the query
                         */
                        const response = (await performQuery(query)) as {
                            results: FunnelStep[] | FunnelStep[][]
                        }

                        if (!response?.results) {
                            throw new Error('No results returned from query')
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
