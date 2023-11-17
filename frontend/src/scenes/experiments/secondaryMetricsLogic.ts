import { actions, connect, kea, listeners, path, props, key, reducers } from 'kea'
import { forms } from 'kea-forms'
import { dayjs } from 'lib/dayjs'

import { Experiment, FilterType, FunnelVizType, InsightType, SecondaryExperimentMetric } from '~/types'
import { cleanFilters, getDefaultEvent } from 'scenes/insights/utils/cleanFilters'
import { FunnelLayout } from 'lib/constants'
import { InsightVizNode } from '~/queries/schema'

import { SECONDARY_METRIC_INSIGHT_ID } from './constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { teamLogic } from 'scenes/teamLogic'

import type { secondaryMetricsLogicType } from './secondaryMetricsLogicType'

const DEFAULT_DURATION = 14

export interface SecondaryMetricsProps {
    onMetricsChange: (metrics: SecondaryExperimentMetric[]) => void
    initialMetrics: SecondaryExperimentMetric[]
    experimentId: Experiment['id']
    defaultAggregationType?: number
}

export interface SecondaryMetricForm {
    name: string
    filters: Partial<FilterType>
}

const defaultFormValuesGenerator: (
    aggregationType?: number,
    disableAddEventToDefault?: boolean
) => SecondaryMetricForm = (aggregationType, disableAddEventToDefault) => {
    const groupAggregation =
        aggregationType !== undefined ? { math: 'unique_group', math_group_type_index: aggregationType } : {}

    const eventAddition = disableAddEventToDefault ? {} : { events: [{ ...getDefaultEvent(), ...groupAggregation }] }

    return {
        name: '',
        filters: {
            insight: InsightType.TRENDS,
            ...eventAddition,
        },
    }
}

export const secondaryMetricsLogic = kea<secondaryMetricsLogicType>([
    props({} as SecondaryMetricsProps),
    key((props) => `${props.experimentId || 'new'}-${props.defaultAggregationType}`),
    path((key) => ['scenes', 'experiment', 'secondaryMetricsLogic', key]),
    connect(() => ({
        logic: [insightLogic({ dashboardItemId: SECONDARY_METRIC_INSIGHT_ID, syncWithUrl: false })],
        values: [teamLogic, ['currentTeamId']],
        actions: [
            insightDataLogic({ dashboardItemId: SECONDARY_METRIC_INSIGHT_ID }),
            ['setQuery'],
            insightVizDataLogic({ dashboardItemId: SECONDARY_METRIC_INSIGHT_ID }),
            ['updateQuerySource'],
        ],
    })),
    actions({
        // modal
        openModalToCreateSecondaryMetric: true,
        openModalToEditSecondaryMetric: (metric: SecondaryExperimentMetric, metricIdx: number) => ({
            metric,
            metricIdx,
        }),
        saveSecondaryMetric: true,
        closeModal: true,

        // metrics
        setMetricId: (metricIdx: number) => ({ metricIdx }),
        addNewMetric: (metric: SecondaryExperimentMetric) => ({ metric }),
        updateMetric: (metric: SecondaryExperimentMetric, metricIdx: number) => ({ metric, metricIdx }),
        deleteMetric: (metricIdx: number) => ({ metricIdx }),

        // preview insight
        setPreviewInsight: (filters?: Partial<FilterType>) => ({ filters }),
    }),
    reducers(({ props }) => ({
        isModalOpen: [
            false,
            {
                openModalToCreateSecondaryMetric: () => true,
                openModalToEditSecondaryMetric: () => true,
                closeModal: () => false,
            },
        ],
        existingModalSecondaryMetric: [
            null as SecondaryExperimentMetric | null,
            {
                openModalToCreateSecondaryMetric: () => null,
                openModalToEditSecondaryMetric: (_, { metric }) => metric,
            },
        ],
        metrics: [
            props.initialMetrics,
            {
                addNewMetric: (metrics, { metric }) => {
                    return [...metrics, { ...metric }]
                },
                updateMetric: (metrics, { metric, metricIdx }) => {
                    const metricsCopy = [...metrics]
                    metricsCopy[metricIdx] = metric
                    return metricsCopy
                },
                deleteMetric: (metrics, { metricIdx }) => metrics.filter((_, idx) => idx !== metricIdx),
            },
        ],
        metricIdx: [
            0 as number,
            {
                setMetricId: (_, { metricIdx }) => metricIdx,
            },
        ],
    })),
    forms(({ props }) => ({
        secondaryMetricModal: {
            defaults: defaultFormValuesGenerator(props.defaultAggregationType),
            errors: () => ({}),
            submit: async () => {
                // We don't use the form submit anymore
            },
        },
    })),
    listeners(({ props, actions, values }) => ({
        openModalToCreateSecondaryMetric: () => {
            actions.resetSecondaryMetricModal()
            actions.setPreviewInsight(defaultFormValuesGenerator(props.defaultAggregationType).filters)
        },
        openModalToEditSecondaryMetric: ({ metric: { name, filters }, metricIdx }) => {
            actions.setSecondaryMetricModalValue('name', name)
            actions.setPreviewInsight(filters)
            actions.setMetricId(metricIdx)
        },
        setPreviewInsight: async ({ filters }) => {
            let newInsightFilters
            if (filters?.insight === InsightType.FUNNELS) {
                newInsightFilters = cleanFilters({
                    insight: InsightType.FUNNELS,
                    funnel_viz_type: FunnelVizType.Steps,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DD'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    layout: FunnelLayout.horizontal,
                    aggregation_group_type_index: props.defaultAggregationType,
                    ...filters,
                })
            } else {
                newInsightFilters = cleanFilters({
                    insight: InsightType.TRENDS,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DD'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    ...defaultFormValuesGenerator(
                        props.defaultAggregationType,
                        (filters?.actions?.length || 0) + (filters?.events?.length || 0) > 0
                    ).filters,
                    ...filters,
                })
            }

            actions.updateQuerySource(filtersToQueryNode(newInsightFilters))
        },
        // sync form value `filters` with query
        setQuery: ({ query }) => {
            actions.setSecondaryMetricModalValue('filters', queryNodeToFilter((query as InsightVizNode).source))
        },
        saveSecondaryMetric: () => {
            if (values.existingModalSecondaryMetric) {
                actions.updateMetric(values.secondaryMetricModal, values.metricIdx)
            } else {
                actions.addNewMetric(values.secondaryMetricModal)
            }
            props.onMetricsChange(values.metrics)
            actions.closeModal()
        },
        deleteMetric: () => {
            props.onMetricsChange(values.metrics)
        },
    })),
])
