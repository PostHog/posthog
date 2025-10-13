import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

import { UserBasicType } from '~/types'

import { getDefaultFunnelMetric } from '../utils'
import type { sharedMetricLogicType } from './sharedMetricLogicType'
import { sharedMetricsLogic } from './sharedMetricsLogic'

export interface SharedMetricLogicProps {
    sharedMetricId?: number | null
    action: 'create' | 'update' | 'duplicate'
}

export interface SharedMetric {
    id: number
    name: string
    description?: string
    query: Record<string, any>
    created_by: UserBasicType | null
    created_at: string | null
    updated_at: string | null
    tags: string[]
    metadata?: Record<string, any>
}

export const NEW_SHARED_METRIC: Partial<SharedMetric> = {
    name: '',
    description: '',
    query: undefined,
    tags: [],
}

export const sharedMetricLogic = kea<sharedMetricLogicType>([
    props({} as SharedMetricLogicProps),
    path((key) => ['scenes', 'experiments', 'sharedMetricLogic', key]),
    key((props) => `${props.sharedMetricId ?? 'new'}-${props.action}`),

    connect(() => ({
        actions: [sharedMetricsLogic, ['loadSharedMetrics'], eventUsageLogic, ['reportExperimentSharedMetricCreated']],
        values: [featureFlagLogic, ['featureFlags'], billingLogic, ['billing']],
    })),

    actions({
        setSharedMetric: (metric: Partial<SharedMetric>) => ({ metric }),
        createSharedMetric: true,
        updateSharedMetric: true,
        deleteSharedMetric: true,
    }),

    loaders(({ props, values }) => ({
        sharedMetric: {
            loadSharedMetric: async () => {
                const { sharedMetricId } = props

                if (sharedMetricId) {
                    const response = await api.get(`api/projects/@current/experiment_saved_metrics/${sharedMetricId}`)
                    return response as SharedMetric
                }

                return {
                    ...values.newSharedMetric,
                }
            },
        },
    })),

    listeners(({ actions, props, values }) => ({
        /**
         * we need to wait for the metric to load to check if we need to modify the name and id
         */
        loadSharedMetricSuccess: () => {
            if (props.action === 'duplicate' && values.sharedMetric) {
                // Generate a new UUID for the duplicated metric's query
                const duplicatedQuery = {
                    ...values.sharedMetric.query,
                    uuid: crypto.randomUUID(),
                }

                actions.setSharedMetric({
                    ...values.sharedMetric,
                    query: duplicatedQuery,
                    name: `${values.sharedMetric.name} (duplicate)`,
                    id: undefined,
                })
            }
        },
        createSharedMetric: async () => {
            const response = await api.create(`api/projects/@current/experiment_saved_metrics/`, values.sharedMetric)
            if (response.id) {
                lemonToast.success('Shared metric created successfully')
                actions.reportExperimentSharedMetricCreated(response as SharedMetric)
                actions.loadSharedMetrics()
                router.actions.push('/experiments?tab=shared-metrics')
            }
        },
        updateSharedMetric: async () => {
            const response = await api.update(
                `api/projects/@current/experiment_saved_metrics/${values.sharedMetricId}`,
                values.sharedMetric
            )
            if (response.id) {
                lemonToast.success('Shared metric updated successfully')
                actions.loadSharedMetrics()
                router.actions.push('/experiments?tab=shared-metrics')
            }
        },
        deleteSharedMetric: async () => {
            try {
                await api.delete(`api/projects/@current/experiment_saved_metrics/${values.sharedMetricId}`)
                lemonToast.success('Shared metric deleted successfully')
                actions.loadSharedMetrics()
                router.actions.push('/experiments?tab=shared-metrics')
            } catch (error) {
                lemonToast.error('Failed to delete shared metric')
                console.error(error)
            }
        },
    })),

    reducers({
        sharedMetric: [
            { ...NEW_SHARED_METRIC } as Partial<SharedMetric>,
            {
                setSharedMetric: (state, { metric }) => ({ ...state, ...metric }),
            },
        ],
    }),

    selectors({
        sharedMetricId: [
            () => [(_, props) => props.sharedMetricId ?? 'new'],
            (sharedMetricId): string | number => sharedMetricId,
        ],
        action: [(_, p) => [p.action], (action) => action],
        newSharedMetric: [
            () => [],
            () => ({
                ...NEW_SHARED_METRIC,
                query: getDefaultFunnelMetric(),
            }),
        ],
    }),

    urlToAction(({ actions, values }) => ({
        '/experiments/shared-metrics/:id': ({ id }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.setSharedMetric({ ...values.newSharedMetric, query: getDefaultFunnelMetric() })
                }

                if (parsedId !== 'new' && parsedId === values.sharedMetricId) {
                    actions.loadSharedMetric()
                }
            }
        },
        '/experiments/shared-metrics/:id/:action': ({ id }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (id && didPathChange) {
                actions.loadSharedMetric()
            }
        },
    })),
])
