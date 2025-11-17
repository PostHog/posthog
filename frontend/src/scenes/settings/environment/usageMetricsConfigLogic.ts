import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import type { usageMetricsConfigLogicType } from './usageMetricsConfigLogicType'

export interface UsageMetric {
    id: string
    name: string
    format: string
    interval: number
    display: string
    filters: object
}

export interface UsageMetricFormData {
    id?: string
    name: string
    format: string
    interval: number
    display: string
    filters: object
}

const NEW_USAGE_METRIC = {
    format: 'numeric',
    interval: 7,
    display: 'number',
    filters: {},
} as UsageMetricFormData

export interface UsageMetricsConfigLogicProps {
    logicKey?: string
}

export const usageMetricsConfigLogic = kea<usageMetricsConfigLogicType>([
    path(['scenes', 'settings', 'environment', 'usageMetricsConfigLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    props({} as UsageMetricsConfigLogicProps),
    key(({ logicKey }) => logicKey || 'defaultKey'),

    actions(() => ({
        setIsEditing: (isEditing: boolean) => ({ isEditing }),
        addUsageMetric: (metric: UsageMetricFormData) => ({ metric }),
        updateUsageMetric: (metric: UsageMetricFormData) => ({ metric }),
        removeUsageMetric: (id: string) => ({ id }),
    })),

    reducers(() => ({
        isEditing: [false, { setIsEditing: (_, { isEditing }) => isEditing }],
    })),

    lazyLoaders(({ values }) => ({
        usageMetrics: [
            [] as UsageMetric[],
            {
                loadUsageMetrics: async () => {
                    return await api.get(values.metricsUrl).then((response) => response.results)
                },
                addUsageMetric: async ({ metric }) => {
                    return await api.create(values.metricsUrl, metric)
                },
                updateUsageMetric: async ({ metric }) => {
                    return await api.update(`${values.metricsUrl}/${metric.id}`, metric)
                },
                removeUsageMetric: async ({ id }) => {
                    return await api.delete(`${values.metricsUrl}/${id}`)
                },
            },
        ],
    })),

    selectors({
        metricsUrl: [
            (s) => [s.currentProjectId],
            // Defaulting group type index to 0 as we want to make this group-agnostic.
            // Backend model/endpoint will be refactored
            (currentProjectId) => `/api/projects/${currentProjectId}/groups_types/0/metrics`,
        ],
    }),

    forms(({ actions }) => ({
        usageMetric: {
            defaults: NEW_USAGE_METRIC,
            errors: ({ name }) => ({
                name: !name ? 'Name is required' : undefined,
            }),
            submit: (formData) => {
                if (formData?.id) {
                    actions.updateUsageMetric(formData)
                } else {
                    actions.addUsageMetric(formData)
                }
            },
        },
    })),

    listeners(({ actions }) => ({
        submitUsageMetricSuccess: () => {
            actions.setIsEditing(false)
            actions.resetUsageMetric()
        },
        addUsageMetricSuccess: () => {
            actions.loadUsageMetrics()
        },
        updateUsageMetricSuccess: () => {
            actions.loadUsageMetrics()
        },
        removeUsageMetricSuccess: () => {
            actions.loadUsageMetrics()
        },
    })),
])
