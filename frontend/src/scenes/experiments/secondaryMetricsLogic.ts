import { actions, connect, events, kea, listeners, path, props, key, reducers } from 'kea'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import {
    Experiment,
    FilterType,
    FunnelVizType,
    InsightModel,
    InsightShortId,
    InsightType,
    SecondaryExperimentMetric,
} from '~/types'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { FunnelLayout } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

import type { secondaryMetricsLogicType } from './secondaryMetricsLogicType'
import { dayjs } from 'lib/dayjs'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

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
    connect({ values: [teamLogic, ['currentTeamId']] }),
    actions({
        openModalToCreateSecondaryMetric: true,
        openModalToEditSecondaryMetric: (metric: SecondaryExperimentMetric, metricId: number) => ({
            metric,
            metricId,
        }),
        closeModal: true,
        addNewMetric: (metric: SecondaryExperimentMetric) => ({ metric }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setPreviewInsightId: (shortId: InsightShortId) => ({ shortId }),
        createPreviewInsight: (filters?: Partial<FilterType>) => ({ filters }),
        deleteMetric: (metricId: number) => ({ metricId }),
        updateMetric: (metric: SecondaryExperimentMetric, metricId: number) => ({ metric, metricId }),
        setMetricId: (metricId: number) => ({ metricId }),
        saveSecondaryMetric: true,
    }),
    loaders(({ values }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async () => {
                    const response = await api.get(`api/projects/${values.currentTeamId}/experiments`)
                    return response.results as Experiment[]
                },
            },
        ],
    })),
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
        previewInsightId: [
            null as InsightShortId | null,
            {
                setPreviewInsightId: (_, { shortId }) => shortId,
            },
        ],
        metrics: [
            props.initialMetrics,
            {
                addNewMetric: (metrics, { metric }) => {
                    return [...metrics, { ...metric }]
                },
                deleteMetric: (metrics, { metricId }) => metrics.filter((_, idx) => idx !== metricId),
                updateMetric: (metrics, { metric, metricId }) => {
                    const metricsCopy = [...metrics]
                    metricsCopy[metricId] = metric
                    return metricsCopy
                },
            },
        ],
        metricId: [
            0 as number,
            {
                setMetricId: (_, { metricId }) => metricId,
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
        openModalToEditSecondaryMetric: ({ metric: { name, filters }, metricId }) => {
            actions.setSecondaryMetricModalValue('name', name)
            actions.createPreviewInsight(filters)
            actions.setMetricId(metricId)
        },
        openModalToCreateSecondaryMetric: () => {
            actions.resetSecondaryMetricModal()
            actions.createPreviewInsight(defaultFormValues.filters)
        },
        createPreviewInsight: async ({ filters }) => {
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

            const newInsight = {
                description: '',
                tags: [],
                filters: newInsightFilters,
                result: null,
            }

            const createdInsight: InsightModel = await api.create(
                `api/projects/${teamLogic.values.currentTeamId}/insights`,
                newInsight
            )
            actions.setPreviewInsightId(createdInsight.short_id)
            actions.setSecondaryMetricModalValue('filters', newInsight.filters)
        },
        setFilters: ({ filters }) => {
            if (filters.insight === InsightType.FUNNELS) {
                funnelLogic.findMounted({ dashboardItemId: values.previewInsightId })?.actions.setFilters(filters)
            } else {
                trendsLogic.findMounted({ dashboardItemId: values.previewInsightId })?.actions.setFilters(filters)
            }
        },
        saveSecondaryMetric: () => {
            if (values.existingModalSecondaryMetric) {
                actions.updateMetric(values.secondaryMetricModal, values.metricId)
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
    events(({ actions }) => ({
        afterMount: () => {
            actions.createPreviewInsight()
        },
    })),
])
