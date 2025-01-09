import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'

import { UserBasicType } from '~/types'

import { getDefaultTrendsMetric } from '../experimentLogic'
import type { savedMetricLogicType } from './savedMetricLogicType'
import { savedMetricsLogic } from './savedMetricsLogic'

export interface SavedMetricLogicProps {
    savedMetricId?: string | number
}

export interface SavedMetric {
    id: number
    name: string
    description?: string
    query: Record<string, any>
    created_by: UserBasicType | null
    created_at: string | null
    updated_at: string | null
}

export const NEW_SAVED_METRIC: Partial<SavedMetric> = {
    name: '',
    description: '',
    query: getDefaultTrendsMetric(),
}

export const savedMetricLogic = kea<savedMetricLogicType>([
    props({} as SavedMetricLogicProps),
    path((key) => ['scenes', 'experiments', 'savedMetricLogic', key]),
    key((props) => props.savedMetricId || 'new'),
    connect(() => ({
        actions: [savedMetricsLogic, ['loadSavedMetrics']],
    })),
    actions({
        setSavedMetric: (metric: Partial<SavedMetric>) => ({ metric }),
        createSavedMetric: true,
        updateSavedMetric: true,
        deleteSavedMetric: true,
    }),

    loaders(({ props }) => ({
        savedMetric: {
            loadSavedMetric: async () => {
                if (props.savedMetricId && props.savedMetricId !== 'new') {
                    const response = await api.get(
                        `api/projects/@current/experiment_saved_metrics/${props.savedMetricId}`
                    )
                    return response as SavedMetric
                }
                return { ...NEW_SAVED_METRIC }
            },
        },
    })),

    listeners(({ actions, values }) => ({
        createSavedMetric: async () => {
            const response = await api.create(`api/projects/@current/experiment_saved_metrics/`, values.savedMetric)
            if (response.id) {
                lemonToast.success('Shared metric created successfully')
                actions.loadSavedMetrics()
                router.actions.push('/experiments/shared-metrics')
            }
        },
        updateSavedMetric: async () => {
            const response = await api.update(
                `api/projects/@current/experiment_saved_metrics/${values.savedMetricId}`,
                values.savedMetric
            )
            if (response.id) {
                lemonToast.success('Shared metric updated successfully')
                actions.loadSavedMetrics()
                router.actions.push('/experiments/shared-metrics')
            }
        },
        deleteSavedMetric: async () => {
            try {
                await api.delete(`api/projects/@current/experiment_saved_metrics/${values.savedMetricId}`)
                lemonToast.success('Shared metric deleted successfully')
                actions.loadSavedMetrics()
                router.actions.push('/experiments/shared-metrics')
            } catch (error) {
                lemonToast.error('Failed to delete shared metric')
                console.error(error)
            }
        },
    })),

    reducers({
        savedMetric: [
            { ...NEW_SAVED_METRIC } as Partial<SavedMetric>,
            {
                setSavedMetric: (state, { metric }) => ({ ...state, ...metric }),
            },
        ],
    }),

    selectors({
        savedMetricId: [
            () => [(_, props) => props.savedMetricId ?? 'new'],
            (savedMetricId): string | number => savedMetricId,
        ],
        isNew: [(s) => [s.savedMetricId], (savedMetricId) => savedMetricId === 'new'],
    }),

    urlToAction(({ actions, values }) => ({
        '/experiments/shared-metrics/:id': ({ id }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.setSavedMetric({ ...NEW_SAVED_METRIC })
                }

                if (parsedId !== 'new' && parsedId === values.savedMetricId) {
                    actions.loadSavedMetric()
                }
            }
        },
    })),
])
