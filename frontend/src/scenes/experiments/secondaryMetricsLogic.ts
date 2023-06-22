import { actions, connect, kea, listeners, path, props, key, reducers } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment, FilterType, FunnelVizType, InsightType, SecondaryExperimentMetric } from '~/types'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { FunnelLayout } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

import type { secondaryMetricsLogicType } from './secondaryMetricsLogicType'
import { dayjs } from 'lib/dayjs'
import { forms } from 'kea-forms'
import { insightLogic } from 'scenes/insights/insightLogic'
import { PREVIEW_INSIGHT_ID } from './constants'

const DEFAULT_DURATION = 14

export interface SecondaryMetricsProps {
    onMetricsChange: (metrics: SecondaryExperimentMetric[]) => void
    initialMetrics: SecondaryExperimentMetric[]
    experimentId: Experiment['id']
}

export interface SecondaryMetricForm {
    name: string
    filters: Partial<FilterType>
}

const defaultFormValues: SecondaryMetricForm = {
    name: '',
    filters: {
        insight: InsightType.TRENDS,
        events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
    },
}

export const secondaryMetricsLogic = kea<secondaryMetricsLogicType>([
    props({} as SecondaryMetricsProps),
    key((props) => props.experimentId || 'new'),
    path((key) => ['scenes', 'experiment', 'secondaryMetricsLogic', key]),
    connect({
        logic: [insightLogic({ dashboardItemId: PREVIEW_INSIGHT_ID, syncWithUrl: false })],
        values: [teamLogic, ['currentTeamId']],
        actions: [
            trendsLogic({ dashboardItemId: PREVIEW_INSIGHT_ID }),
            ['setFilters as setTrendsFilters'],
            funnelLogic({ dashboardItemId: PREVIEW_INSIGHT_ID }),
            ['setFilters as setFunnelFilters'],
        ],
    }),
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
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
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
    forms(() => ({
        secondaryMetricModal: {
            defaults: defaultFormValues as SecondaryMetricForm,
            errors: () => ({}),
            submit: async () => {
                // We don't use the form submit anymore
            },
        },
    })),
    listeners(({ props, actions, values }) => ({
        openModalToCreateSecondaryMetric: () => {
            actions.resetSecondaryMetricModal()
            actions.setPreviewInsight(defaultFormValues.filters)
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
                    ...filters,
                })
            } else {
                newInsightFilters = cleanFilters({
                    insight: InsightType.TRENDS,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DD'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    ...filters,
                })
            }

            actions.setSecondaryMetricModalValue('filters', newInsightFilters)
            actions.setFilters(newInsightFilters)
        },
        setFilters: ({ filters }) => {
            if (filters.insight === InsightType.FUNNELS) {
                actions.setFunnelFilters(filters)
            } else {
                actions.setTrendsFilters(filters)
            }
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
