import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { groupsModel } from '~/models/groupsModel'

import type { crmUsageMetricsConfigLogicType } from './crmUsageMetricsConfigLogicType'
import { loaders } from 'kea-loaders'
import { projectLogic } from 'scenes/projectLogic'
import api from 'lib/api'

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
} as UsageMetricFormData

export const crmUsageMetricsConfigLogic = kea<crmUsageMetricsConfigLogicType>([
    path(['scenes', 'settings', 'environment', 'crmUsageMetricsConfigLogic']),
    connect(() => ({
        values: [groupsModel, ['groupTypes', 'groupTypesLoading'], projectLogic, ['currentProjectId']],
    })),

    actions(() => ({
        setIsEditing: (isEditing: boolean) => ({ isEditing }),
        setCurrentGroupTypeIndex: (groupTypeIndex: number) => ({ groupTypeIndex }),
        addUsageMetric: (metric: UsageMetricFormData) => ({ metric }),
        updateUsageMetric: (metric: UsageMetricFormData) => ({ metric }),
        removeUsageMetric: (id: string) => ({ id }),
    })),

    reducers(() => ({
        isEditing: [false, { setIsEditing: (_, { isEditing }) => isEditing }],
        currentGroupTypeIndex: [0, { setCurrentGroupTypeIndex: (_, { groupTypeIndex }) => groupTypeIndex }],
    })),

    loaders(({ values }) => ({
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
        currentGroupTypeUsageMetrics: [(s) => [s.usageMetrics], (usageMetrics) => usageMetrics],
        availableGroupTypes: [(s) => [s.groupTypes], (groupTypes) => Array.from(groupTypes.values())],
        metricsUrl: [
            (s) => [s.currentGroupTypeIndex, s.currentProjectId],
            (currentGroupTypeIndex, currentProjectId) =>
                `/api/projects/${currentProjectId}/groups_types/${currentGroupTypeIndex}/metrics`,
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
        setCurrentGroupTypeIndex: () => {
            actions.loadUsageMetrics()
        },
    })),

    afterMount(({ actions }) => actions.loadUsageMetrics()),
])
