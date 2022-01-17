import { kea } from 'kea'
import { api } from 'lib/api.mock'
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
import dayjs from 'dayjs'
import { FunnelLayout } from 'lib/constants'
import { generateRandomAnimal } from 'lib/utils/randomAnimal'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

import { secondaryMetricsLogicType } from './secondaryMetricsLogicType'

const DEFAULT_DURATION = 14

export interface SecondaryMetricsProps {
    onMetricsChange: (metrics: SecondaryExperimentMetric[]) => void
    initialMetrics: SecondaryExperimentMetric[]
}

export const secondaryMetricsLogic = kea<secondaryMetricsLogicType<SecondaryMetricsProps>>({
    props: {} as SecondaryMetricsProps,
    path: ['scenes', 'experiment', 'secondaryMetricsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setSecondaryMetrics: (secondaryMetrics: any) => ({ secondaryMetrics }),
        createNewMetric: (metricType: InsightType) => ({ metricType }),
        updateMetricFilters: (metricId: number, filters: Partial<FilterType>) => ({ metricId, filters }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setPreviewInsightId: (shortId: InsightShortId) => ({ shortId }),
        createPreviewInsight: (filters?: Partial<FilterType>) => ({ filters }),
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
                createNewMetric: (metrics, { metricType }) => {
                    return [
                        ...metrics,
                        {
                            filters: {
                                insight: metricType,
                                events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
                                layout: FunnelLayout.horizontal,
                                display: ChartDisplayType.ActionsLineGraphCumulative,
                            },
                        },
                    ]
                },
                updateMetricFilters: (metrics, { metricId, filters }) => {
                    return metrics.map((metric, index) => (index === metricId ? { ...metric, filters } : metric))
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
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    layout: FunnelLayout.horizontal,
                    ...filters,
                })
            } else {
                newInsightFilters = cleanFilters({
                    insight: InsightType.TRENDS,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    ...filters,
                })
            }

            const newInsight = {
                name: generateRandomAnimal(),
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
            props.onMetricsChange(values.metrics)
        },
        updateMetricFilters: () => {
            props.onMetricsChange(values.metrics)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.createPreviewInsight()
        },
    }),
})
