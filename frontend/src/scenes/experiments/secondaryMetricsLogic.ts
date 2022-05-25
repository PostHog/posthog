import { kea } from 'kea'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import {
    ChartDisplayType,
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

const DEFAULT_DURATION = 14
const BASIC_TRENDS_INSIGHT = {
    name: '',
    filters: {
        insight: InsightType.TRENDS,
        events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
    },
}

const BASIC_FUNNELS_INSIGHT = {
    name: '',
    filters: {
        insight: InsightType.FUNNELS,
        events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
        layout: FunnelLayout.horizontal,
    },
}

export interface SecondaryMetricsProps {
    onMetricsChange: (metrics: SecondaryExperimentMetric[]) => void
    initialMetrics: SecondaryExperimentMetric[]
}

export const secondaryMetricsLogic = kea<secondaryMetricsLogicType>({
    props: {} as SecondaryMetricsProps,
    path: ['scenes', 'experiment', 'secondaryMetricsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setSecondaryMetrics: (secondaryMetrics: any) => ({ secondaryMetrics }),
        createNewMetric: true,
        addNewMetric: (metric: SecondaryExperimentMetric) => ({ metric }),
        updateMetricFilters: (filters: Partial<FilterType>) => ({ filters }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setPreviewInsightId: (shortId: InsightShortId) => ({ shortId }),
        createPreviewInsight: (filters?: Partial<FilterType>) => ({ filters }),
        showModal: true,
        hideModal: true,
        changeInsightType: (type?: InsightType) => ({ type }),
        setCurrentMetricName: (name: string) => ({ name }),
        deleteMetric: (metricId: number) => ({ metricId }),
    },
    loaders: ({ values }) => ({
        experiments: [
            [] as Experiment[],
            {
                loadExperiments: async () => {
                    const response = await api.get(`api/projects/${values.currentTeamId}/experiments`)
                    return response.results as Experiment[]
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
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
            },
        ],
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
            },
        ],
        currentMetricName: [
            '',
            {
                setCurrentMetricName: (_, { name }) => name,
            },
        ],
        currentMetric: [
            BASIC_TRENDS_INSIGHT as SecondaryExperimentMetric,
            {
                changeInsightType: (metric, { type }) => {
                    if (type === InsightType.TRENDS) {
                        return BASIC_TRENDS_INSIGHT
                    }
                    if (metric.filters.insight === InsightType.TRENDS) {
                        return BASIC_FUNNELS_INSIGHT
                    }
                    return BASIC_TRENDS_INSIGHT
                },
                updateMetricFilters: (metric, { filters }) => {
                    return { ...metric, filters }
                },
            },
        ],
    }),
    listeners: ({ actions, values, props }) => ({
        createPreviewInsight: async ({ filters }) => {
            let newInsightFilters
            if (filters?.insight === InsightType.FUNNELS) {
                newInsightFilters = cleanFilters({
                    insight: InsightType.FUNNELS,
                    funnel_viz_type: FunnelVizType.Steps,
                    display: ChartDisplayType.FunnelViz,
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
        },
        setFilters: ({ filters }) => {
            if (filters.insight === InsightType.FUNNELS) {
                funnelLogic.findMounted({ dashboardItemId: values.previewInsightId })?.actions.setFilters(filters)
            } else {
                trendsLogic.findMounted({ dashboardItemId: values.previewInsightId })?.actions.setFilters(filters)
            }
        },
        createNewMetric: () => {
            actions.addNewMetric({ ...values.currentMetric, name: values.currentMetricName })
            props.onMetricsChange(values.metrics)
            actions.changeInsightType(InsightType.TRENDS)
            actions.setCurrentMetricName('')
        },
        deleteMetric: () => {
            props.onMetricsChange(values.metrics)
        },
        changeInsightType: () => actions.createPreviewInsight(values.currentMetric.filters),
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.createPreviewInsight()
        },
    }),
})
