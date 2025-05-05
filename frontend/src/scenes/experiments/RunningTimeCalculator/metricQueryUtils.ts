import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import type { ExperimentMetric, FunnelsQuery } from '~/queries/schema/schema-general'
import type { TrendsQuery } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import { ExperimentMetricType, isExperimentFunnelMetric, isExperimentMeanMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'
import { BaseMathType, CountPerActorMathType, FunnelVizType, PropertyMathType } from '~/types'

import type { EventConfig } from './runningTimeCalculatorLogic'

const getKindField = (metric: ExperimentMetric): NodeKind => {
    if (isExperimentFunnelMetric(metric)) {
        return NodeKind.EventsNode
    }

    if (isExperimentMeanMetric(metric)) {
        const { kind } = metric.source
        // For most sources, we can return the kind directly
        if ([NodeKind.EventsNode, NodeKind.ActionsNode, NodeKind.ExperimentDataWarehouseNode].includes(kind)) {
            return kind
        }
    }

    return NodeKind.EventsNode
}

const getEventField = (metric: ExperimentMetric): string | number | null | undefined => {
    if (isExperimentMeanMetric(metric)) {
        const { source } = metric
        return source.kind === NodeKind.ExperimentDataWarehouseNode
            ? source.table_name
            : source.kind === NodeKind.EventsNode
            ? source.event
            : source.kind === NodeKind.ActionsNode
            ? source.id
            : null
    }

    if (isExperimentFunnelMetric(metric)) {
        /**
         * For multivariate funnels, we select the last step
         * Although we know that the last step is always an EventsNode, TS infers that the last step might be undefined
         * so we use the non-null assertion operator (!) to tell TS that we know the last step is always an EventsNode
         */
        const step = metric.series.at(-1)!
        return step.kind === NodeKind.EventsNode ? step.event : step.kind === NodeKind.ActionsNode ? step.id : null
    }

    return null
}

export const getTotalCountQuery = (metric: ExperimentMetric, experiment: Experiment): TrendsQuery => {
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: getKindField(metric),
                event: getEventField(metric),
                math: BaseMathType.UniqueUsers,
            },
            {
                kind: getKindField(metric),
                event: getEventField(metric),
                math: CountPerActorMathType.Average,
            },
        ],
        trendsFilter: {},
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: {
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            explicitDate: true,
        },
    } as TrendsQuery
}

export const getSumQuery = (metric: ExperimentMetric, experiment: Experiment): TrendsQuery => {
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: getKindField(metric),
                event: getEventField(metric),
                math: BaseMathType.UniqueUsers,
            },
            {
                kind: getKindField(metric),
                event: getEventField(metric),
                math: PropertyMathType.Sum,
                math_property_type: TaxonomicFilterGroupType.NumericalEventProperties,
                ...(metric.metric_type === ExperimentMetricType.MEAN && {
                    math_property: metric.source.math_property,
                }),
            },
        ],
        trendsFilter: {},
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: {
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            explicitDate: true,
        },
    } as TrendsQuery
}

export const getFunnelQuery = (
    metric: ExperimentMetric,
    eventConfig: EventConfig | null,
    experiment: Experiment
): FunnelsQuery => {
    return {
        kind: NodeKind.FunnelsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: eventConfig?.event ?? '$pageview',
                properties: eventConfig?.properties ?? [],
            },
            {
                kind: getKindField(metric),
                event: getEventField(metric),
            },
        ],
        funnelsFilter: {
            funnelVizType: FunnelVizType.Steps,
        },
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: {
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            explicitDate: true,
        },
        interval: 'day',
    } as FunnelsQuery
}
