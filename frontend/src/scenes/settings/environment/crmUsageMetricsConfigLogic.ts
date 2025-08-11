import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
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
}

export interface NewUsageMetricFormData {
    id?: string
    name: string
    format: string
    interval: string
    display: string
    events: string[]
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
        addUsageMetric: (metric: NewUsageMetricFormData) => ({ metric }),
        updateUsageMetric: (metric: NewUsageMetricFormData) => ({ metric }),
        removeUsageMetric: (id: string) => ({ id }),
    })),

    reducers(() => ({
        isEditing: [false, { setIsEditing: (_, { isEditing }) => isEditing }],
    })),

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
    })),

    afterMount(({ actions }) => actions.loadUsageMetrics()),

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
                        },
                        {
                            id: '2',
                            name: 'Replay',
                            format: 'numeric',
                            display: 'sparkline',
                            interval: '7d',
                            events: [],
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
])
