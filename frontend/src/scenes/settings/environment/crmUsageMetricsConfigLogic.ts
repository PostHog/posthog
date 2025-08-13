import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { groupsModel } from '~/models/groupsModel'

import type { crmUsageMetricsConfigLogicType } from './crmUsageMetricsConfigLogicType'
import { loaders } from 'kea-loaders'

export interface UsageMetric {
    id: string
    name: string
    format: string
    interval: string
    display: string
    events: string[]
    group_type_index: number
}

export interface NewUsageMetricFormData {
    id?: string
    name: string
    format: string
    interval: string
    display: string
    events: string[]
    group_type_index?: number
}

const NEW_USAGE_METRIC = {
    format: 'numeric',
    interval: '7d',
    display: 'number',
} as NewUsageMetricFormData

export const crmUsageMetricsConfigLogic = kea<crmUsageMetricsConfigLogicType>([
    path(['scenes', 'settings', 'environment', 'crmUsageMetricsConfigLogic']),
    connect(() => ({
        values: [groupsModel, ['groupTypes', 'groupTypesLoading']],
    })),

    actions(() => ({
        setIsEditing: (isEditing: boolean) => ({ isEditing }),
        setCurrentGroupTypeIndex: (groupTypeIndex: number) => ({ groupTypeIndex }),
        addUsageMetric: (metric: NewUsageMetricFormData) => ({ metric }),
        updateUsageMetric: (metric: NewUsageMetricFormData) => ({ metric }),
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
                    // Mock API delay
                    await new Promise((resolve) => setTimeout(resolve, 500))
                    return [
                        {
                            id: '1',
                            name: 'Events',
                            format: 'numeric',
                            display: 'number',
                            interval: '7d',
                            events: [],
                            group_type_index: 0,
                        },
                        {
                            id: '2',
                            name: 'Replay',
                            format: 'numeric',
                            display: 'sparkline',
                            interval: '7d',
                            events: [],
                            group_type_index: 0,
                        },
                        {
                            id: '3',
                            name: 'API Calls',
                            format: 'numeric',
                            display: 'number',
                            interval: '30d',
                            events: [],
                            group_type_index: 1,
                        },
                    ] as UsageMetric[]
                },
                addUsageMetric: async ({ metric }) => {
                    // Mock API delay
                    await new Promise((resolve) => setTimeout(resolve, 300))
                    const largestId = values.usageMetrics.reduce((max, m) => Math.max(max, parseInt(m.id, 10)), 0)
                    const newId = (largestId + 1).toString() || '1'
                    const newMetric = {
                        id: newId,
                        ...metric,
                        group_type_index: metric.group_type_index ?? values.currentGroupTypeIndex,
                    }
                    return [...values.usageMetrics, newMetric]
                },
                updateUsageMetric: async ({ metric }) => {
                    // Mock API delay
                    await new Promise((resolve) => setTimeout(resolve, 300))
                    const updatedMetrics = values.usageMetrics.map((oldMetric) =>
                        oldMetric.id === metric.id ? { ...oldMetric, ...metric } : oldMetric
                    )
                    return updatedMetrics
                },
                removeUsageMetric: async ({ id }) => {
                    // Mock API delay
                    await new Promise((resolve) => setTimeout(resolve, 300))
                    return values.usageMetrics.filter((metric) => metric.id !== id)
                },
            },
        ],
    })),

    selectors({
        currentGroupTypeUsageMetrics: [
            (s) => [s.usageMetrics, s.currentGroupTypeIndex],
            (usageMetrics, currentGroupTypeIndex) =>
                usageMetrics.filter((metric) => metric.group_type_index === currentGroupTypeIndex),
        ],
        availableGroupTypes: [(s) => [s.groupTypes], (groupTypes) => Array.from(groupTypes.values())],
    }),

    forms(({ actions, values }) => ({
        usageMetric: {
            defaults: NEW_USAGE_METRIC,
            errors: ({ name }) => ({
                name: !name ? 'Name is required' : undefined,
            }),
            submit: (formData) => {
                const formDataWithGroupType = {
                    ...formData,
                    group_type_index: formData.group_type_index ?? values.currentGroupTypeIndex,
                }
                if (formData?.id) {
                    actions.updateUsageMetric(formDataWithGroupType)
                } else {
                    actions.addUsageMetric(formDataWithGroupType)
                }
            },
        },
    })),

    listeners(({ actions }) => ({
        submitUsageMetricSuccess: () => {
            actions.setIsEditing(false)
            actions.resetUsageMetric()
        },
    })),

    afterMount(({ actions }) => actions.loadUsageMetrics()),
])
