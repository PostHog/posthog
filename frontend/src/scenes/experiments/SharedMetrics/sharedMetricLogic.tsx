import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { UserBasicType } from '~/types'

import { getDefaultTrendsMetric } from '../utils'
import type { sharedMetricLogicType } from './sharedMetricLogicType'
import { sharedMetricsLogic } from './sharedMetricsLogic'

export interface SharedMetricLogicProps {
    sharedMetricId?: string | number
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
}

export const NEW_SHARED_METRIC: Partial<SharedMetric> = {
    name: '',
    description: '',
    query: getDefaultTrendsMetric(),
    tags: [],
}

export const sharedMetricLogic = kea<sharedMetricLogicType>([
    props({} as SharedMetricLogicProps),
    path((key) => ['scenes', 'experiments', 'sharedMetricLogic', key]),
    key((props) => props.sharedMetricId || 'new'),
    connect(() => ({
        actions: [sharedMetricsLogic, ['loadSharedMetrics'], eventUsageLogic, ['reportExperimentSharedMetricCreated']],
    })),
    actions({
        setSharedMetric: (metric: Partial<SharedMetric>) => ({ metric }),
        createSharedMetric: true,
        updateSharedMetric: true,
        deleteSharedMetric: true,
    }),

    loaders(({ props }) => ({
        sharedMetric: {
            loadSharedMetric: async () => {
                if (props.sharedMetricId && props.sharedMetricId !== 'new') {
                    const response = await api.get(
                        `api/projects/@current/experiment_saved_metrics/${props.sharedMetricId}`
                    )
                    return response as SharedMetric
                }
                return { ...NEW_SHARED_METRIC }
            },
        },
    })),

    listeners(({ actions, values }) => ({
        createSharedMetric: async () => {
            const response = await api.create(`api/projects/@current/experiment_saved_metrics/`, values.sharedMetric)
            if (response.id) {
                lemonToast.success('Shared metric created successfully')
                actions.reportExperimentSharedMetricCreated(response as SharedMetric)
                actions.loadSharedMetrics()
                router.actions.push('/experiments/shared-metrics')
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
                router.actions.push('/experiments/shared-metrics')
            }
        },
        deleteSharedMetric: async () => {
            try {
                await api.delete(`api/projects/@current/experiment_saved_metrics/${values.sharedMetricId}`)
                lemonToast.success('Shared metric deleted successfully')
                actions.loadSharedMetrics()
                router.actions.push('/experiments/shared-metrics')
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
        isNew: [(s) => [s.sharedMetricId], (sharedMetricId) => sharedMetricId === 'new'],
    }),

    urlToAction(({ actions, values }) => ({
        '/experiments/shared-metrics/:id': ({ id }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.setSharedMetric({ ...NEW_SHARED_METRIC })
                }

                if (parsedId !== 'new' && parsedId === values.sharedMetricId) {
                    actions.loadSharedMetric()
                }
            }
        },
    })),
])
