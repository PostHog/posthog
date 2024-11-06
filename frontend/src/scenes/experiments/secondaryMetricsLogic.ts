import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { cleanFilters, getDefaultEvent } from 'scenes/insights/utils/cleanFilters'
import { teamLogic } from 'scenes/teamLogic'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelsQuery, InsightVizNode, TrendsQuery } from '~/queries/schema'
import { Experiment, FilterType, FunnelVizType, InsightType, SecondaryExperimentMetric } from '~/types'

import { SECONDARY_METRIC_INSIGHT_ID } from './constants'
import { experimentLogic } from './experimentLogic'
import type { secondaryMetricsLogicType } from './secondaryMetricsLogicType'

const DEFAULT_DURATION = 14

export const MAX_SECONDARY_METRICS = 10

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
    disableAddEventToDefault?: boolean,
    cohortIdToFilter?: number
) => SecondaryMetricForm = (aggregationType, disableAddEventToDefault, cohortIdToFilter) => {
    const groupAggregation =
        aggregationType !== undefined ? { math: 'unique_group', math_group_type_index: aggregationType } : {}

    const cohortFilter = cohortIdToFilter
        ? { properties: [{ key: 'id', type: 'cohort', value: cohortIdToFilter }] }
        : {}
    const eventAddition = disableAddEventToDefault
        ? {}
        : { events: [{ ...getDefaultEvent(), ...groupAggregation, ...cohortFilter }] }

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
    connect((props: SecondaryMetricsProps) => ({
        logic: [insightLogic({ dashboardItemId: SECONDARY_METRIC_INSIGHT_ID, syncWithUrl: false })],
        values: [teamLogic, ['currentTeamId'], experimentLogic({ experimentId: props.experimentId }), ['experiment']],
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
        openModalToEditSecondaryMetric: (
            metric: SecondaryExperimentMetric,
            metricIdx: number,
            showResults: boolean = false
        ) => ({
            metric,
            metricIdx,
            showResults,
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
        showResults: [
            false,
            {
                openModalToEditSecondaryMetric: (_, { showResults }) => showResults,
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
    forms(({ props, values }) => ({
        secondaryMetricModal: {
            defaults: defaultFormValuesGenerator(
                props.defaultAggregationType,
                false,
                values.experiment?.exposure_cohort
            ),
            errors: () => ({}),
            submit: async () => {
                // We don't use the form submit anymore
            },
        },
    })),
    listeners(({ props, actions, values }) => ({
        openModalToCreateSecondaryMetric: () => {
            actions.resetSecondaryMetricModal()
            actions.setPreviewInsight(
                defaultFormValuesGenerator(props.defaultAggregationType, false, values.experiment?.exposure_cohort)
                    .filters
            )
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

            // This allows switching between insight types. It's necessary as `updateQuerySource` merges
            // the new query with any existing query and that causes validation problems when there are
            // unsupported properties in the now merged query.
            const newQuery = filtersToQueryNode(newInsightFilters)
            if (filters?.insight === InsightType.FUNNELS) {
                ;(newQuery as TrendsQuery).trendsFilter = undefined
            } else {
                ;(newQuery as FunnelsQuery).funnelsFilter = undefined
            }
            actions.updateQuerySource(newQuery)
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
