import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import type { ExperimentMetric, FunnelsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import {
    ExperimentMetricType,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import type { Experiment } from '~/types'
import { BaseMathType, CountPerActorMathType, FunnelVizType, PropertyMathType } from '~/types'

import type { EventConfig } from './runningTimeCalculatorLogic'

// Creates the correct identifier properties for a series item based on metric type
const getSeriesItemProps = (metric: ExperimentMetric): { kind: NodeKind } & Record<string, any> => {
    if (isExperimentMeanMetric(metric)) {
        const { source } = metric

        if (source.kind === NodeKind.EventsNode) {
            return {
                kind: NodeKind.EventsNode,
                event: source.event,
                properties: source.properties || [],
            }
        }

        if (source.kind === NodeKind.ActionsNode) {
            return {
                kind: NodeKind.ActionsNode,
                id: source.id,
                properties: source.properties || [],
            }
        }

        if (source.kind === NodeKind.ExperimentDataWarehouseNode) {
            return {
                kind: NodeKind.ExperimentDataWarehouseNode,
                table_name: source.table_name,
                properties: source.properties || [],
            }
        }
    }

    if (isExperimentFunnelMetric(metric)) {
        /**
         * For multivariate funnels, we select the last step
         * Although we know that the last step is always an EventsNode, TS infers that the last step might be undefined
         * so we use the non-null assertion operator (!) to tell TS that we know the last step is always an EventsNode
         */
        const step = metric.series.at(-1)!

        if (step.kind === NodeKind.EventsNode) {
            return {
                kind: NodeKind.EventsNode,
                event: step.event,
                properties: step.properties || [],
            }
        }

        if (step.kind === NodeKind.ActionsNode) {
            return {
                kind: NodeKind.ActionsNode,
                id: step.id,
                properties: step.properties || [],
            }
        }
    }

    throw new Error(`Unsupported metric type: ${metric.metric_type || 'unknown'}`)
}

const getQueryDateRange = (): {
    date_from: string
    date_to: string
    explicitDate: boolean
} => ({
    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
    explicitDate: true,
})

export const getTotalCountQuery = (
    metric: ExperimentMetric,
    experiment: Experiment,
    eventConfig: EventConfig | null
): TrendsQuery => {
    const baseProps = getSeriesItemProps(metric)

    return setLatestVersionsOnQuery({
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: eventConfig?.event ?? '$pageview',
                properties: eventConfig?.properties ?? [],
                math: BaseMathType.UniqueUsers,
            },
            {
                ...baseProps,
                math: CountPerActorMathType.Average,
            },
        ],
        trendsFilter: {},
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: getQueryDateRange(),
    }) as TrendsQuery
}

export const getSumQuery = (
    metric: ExperimentMetric,
    experiment: Experiment,
    eventConfig: EventConfig | null
): TrendsQuery => {
    const baseProps = getSeriesItemProps(metric)
    const mathProperty =
        metric.metric_type === ExperimentMetricType.MEAN
            ? {
                  math_property: metric.source.math_property,
                  math_property_type: TaxonomicFilterGroupType.NumericalEventProperties,
              }
            : {}

    return setLatestVersionsOnQuery({
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: eventConfig?.event ?? '$pageview',
                properties: eventConfig?.properties ?? [],
                math: BaseMathType.UniqueUsers,
            },
            {
                ...baseProps,
                math: PropertyMathType.Sum,
                ...mathProperty,
            },
        ],
        trendsFilter: {},
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: getQueryDateRange(),
    }) as TrendsQuery
}

export const getFunnelQuery = (
    metric: ExperimentMetric,
    experiment: Experiment,
    eventConfig: EventConfig | null
): FunnelsQuery => {
    const baseProps = getSeriesItemProps(metric)

    return setLatestVersionsOnQuery({
        kind: NodeKind.FunnelsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: eventConfig?.event ?? '$pageview',
                properties: eventConfig?.properties ?? [],
            },
            baseProps,
        ],
        funnelsFilter: {
            funnelVizType: FunnelVizType.Steps,
        },
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: getQueryDateRange(),
        interval: 'day',
    }) as FunnelsQuery
}
