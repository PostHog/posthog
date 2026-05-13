import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { lazyLoaders } from 'kea-loaders'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import {
    groupsTypesMetricsCreate,
    groupsTypesMetricsDestroy,
    groupsTypesMetricsList,
    groupsTypesMetricsUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type { GroupUsageMetricApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { usageMetricsConfigLogicType } from './usageMetricsConfigLogicType'

export type UsageMetricSource = 'events' | 'data_warehouse'

export type UsageMetricFiltersDataWarehouse = {
    source: 'data_warehouse'
    table_name?: string | null
    timestamp_field?: string | null
    key_field?: string | null
}

export type UsageMetricFormData = Omit<GroupUsageMetricApi, 'id' | 'filters'> & {
    id?: string
    filters: FilterType | UsageMetricFiltersDataWarehouse
}

const NEW_USAGE_METRIC: UsageMetricFormData = {
    name: '',
    format: 'numeric',
    interval: 7,
    display: 'number',
    filters: {},
    math: 'count',
    math_property: null,
}

export function getMetricSource(filters: UsageMetricFormData['filters']): UsageMetricSource {
    if (
        filters &&
        typeof filters === 'object' &&
        'source' in filters &&
        (filters as UsageMetricFiltersDataWarehouse).source === 'data_warehouse'
    ) {
        return 'data_warehouse'
    }
    return 'events'
}

/**
 * Render the saved filters in the standard FilterType shape that ActionFilter expects.
 * DW metrics get hoisted into a single `data_warehouse` entry; events metrics pass through.
 */
export function savedFiltersToActionFilterValue(filters: UsageMetricFormData['filters']): FilterType {
    if (getMetricSource(filters) === 'data_warehouse') {
        const dw = filters as UsageMetricFiltersDataWarehouse
        return {
            data_warehouse: [
                {
                    type: 'data_warehouse',
                    id: dw.table_name ?? '',
                    name: dw.table_name ?? '',
                    table_name: dw.table_name ?? '',
                    timestamp_field: dw.timestamp_field,
                    key_field: dw.key_field,
                },
            ],
        } as FilterType
    }
    return (filters ?? {}) as FilterType
}

/**
 * Translate ActionFilter's FilterType payload back into our saved shape (events shape or DW shape).
 * If both branches are populated (the user just added an entry of the opposite type), resolve by
 * switching to whichever side just received the new entry — using `prevSource` as the reference.
 */
export function actionFilterValueToSavedFilters(
    payload: FilterType,
    prevSource: UsageMetricSource
): UsageMetricFormData['filters'] {
    const dwEntries = (payload.data_warehouse ?? []) as Array<Record<string, any>>
    const eventEntries = payload.events ?? []
    const actionEntries = payload.actions ?? []

    const switchedToDw = prevSource === 'events' && dwEntries.length > 0
    const onlyDw = dwEntries.length > 0 && eventEntries.length === 0 && actionEntries.length === 0

    if (onlyDw || switchedToDw) {
        const dw = dwEntries[0] ?? {}
        return {
            source: 'data_warehouse',
            table_name: dw.table_name ?? dw.name ?? null,
            timestamp_field: dw.timestamp_field ?? null,
            key_field: dw.key_field ?? null,
        }
    }

    return {
        events: eventEntries,
        actions: actionEntries,
        properties: payload.properties ?? [],
        filter_test_accounts: payload.filter_test_accounts,
    } as FilterType
}

// Hardcoded to 0 — the backend model is coupled to groups but will be refactored to be group-agnostic
const GROUP_TYPE_INDEX = 0

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
            [] as GroupUsageMetricApi[],
            {
                loadUsageMetrics: async () => {
                    const response = await groupsTypesMetricsList(String(values.currentProjectId), GROUP_TYPE_INDEX)
                    return response.results
                },
                addUsageMetric: async ({ metric }) => {
                    const { id: _id, ...payload } = metric
                    const newMetric = await groupsTypesMetricsCreate(
                        String(values.currentProjectId),
                        GROUP_TYPE_INDEX,
                        payload as GroupUsageMetricApi
                    )
                    return [...values.usageMetrics, newMetric]
                },
                updateUsageMetric: async ({ metric }) => {
                    if (!metric.id) {
                        throw new Error('Cannot update a metric without an id')
                    }
                    const updatedMetric = await groupsTypesMetricsUpdate(
                        String(values.currentProjectId),
                        GROUP_TYPE_INDEX,
                        metric.id,
                        metric as GroupUsageMetricApi
                    )
                    return [...values.usageMetrics.filter((m) => m.id !== metric.id), updatedMetric]
                },
                removeUsageMetric: async ({ id }) => {
                    await groupsTypesMetricsDestroy(String(values.currentProjectId), GROUP_TYPE_INDEX, id)
                    return values.usageMetrics.filter((m) => m.id !== id)
                },
            },
        ],
    })),

    forms(({ actions }) => ({
        usageMetric: {
            defaults: NEW_USAGE_METRIC,
            errors: ({ name, math, math_property, filters }) => ({
                name: !name ? 'Name is required' : undefined,
                math_property:
                    math === 'sum' && !math_property
                        ? getMetricSource(filters) === 'data_warehouse'
                            ? 'Column to sum is required'
                            : 'Property is required for sum'
                        : undefined,
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
