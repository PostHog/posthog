import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

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
    props({} as UsageMetricsConfigLogicProps),
    key(({ logicKey }) => logicKey || 'defaultKey'),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
        actions: [
            eventUsageLogic,
            ['reportUsageMetricCreated', 'reportUsageMetricUpdated', 'reportUsageMetricDeleted'],
            teamLogic,
            ['addProductIntent'],
        ],
    })),

    actions(() => ({
        addUsageMetric: (metric: UsageMetricFormData) => ({ metric }),
        updateUsageMetric: (metric: UsageMetricFormData) => ({ metric }),
        removeUsageMetric: (id: string) => ({ id }),
        openModal: true,
        closeModal: true,
    })),

    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
    }),

    lazyLoaders(({ values }) => ({
        usageMetrics: [
            [] as UsageMetric[],
            {
                loadUsageMetrics: async () => {
                    return await api.get(values.metricsUrl).then((response) => response.results)
                },
                addUsageMetric: async ({ metric }) => {
                    const newMetric = await api.create(values.metricsUrl, metric)
                    return [...values.usageMetrics, newMetric]
                },
                updateUsageMetric: async ({ metric }) => {
                    const updatedMetric = await api.update(`${values.metricsUrl}/${metric.id}`, metric)
                    return [...values.usageMetrics.filter((m) => m.id !== metric.id), updatedMetric]
                },
                removeUsageMetric: async ({ id }) => {
                    const deletedMetric = await api.delete(`${values.metricsUrl}/${id}`)
                    return [...values.usageMetrics.filter((m) => m.id !== id), deletedMetric]
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
        closeModal: () => {
            actions.resetUsageMetric()
        },
        submitUsageMetricSuccess: () => {
            actions.loadUsageMetrics()
            actions.closeModal()
        },
        addUsageMetricSuccess: () => {
            actions.loadUsageMetrics()
            actions.reportUsageMetricCreated()
            actions.addProductIntent({
                product_type: ProductKey.CUSTOMER_ANALYTICS,
                intent_context: ProductIntentContext.CUSTOMER_ANALYTICS_USAGE_METRIC_CREATED,
            })
        },
        updateUsageMetricSuccess: () => {
            actions.loadUsageMetrics()
            actions.reportUsageMetricUpdated()
        },
        removeUsageMetricSuccess: () => {
            actions.loadUsageMetrics()
            actions.reportUsageMetricDeleted()
        },
    })),
])
