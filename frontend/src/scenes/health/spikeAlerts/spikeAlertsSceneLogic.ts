import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { spikeAlertsSceneLogicType } from './spikeAlertsSceneLogicType'

export interface DetectedSpike {
    usage_key: string
    value: string | number
    weekday_average: string | number
    z_score: number
    [key: string]: unknown
}

export interface SpikeAlert {
    id: string
    detected_spikes: DetectedSpike[]
    spike_date: string
    detected_at: string
}

export interface SpikeAlertsResponse {
    results: SpikeAlert[]
    count: number
}

export interface FlatSpikeRow {
    rowKey: string
    spike_date: string
    detected_at: string
    usage_key: string
    value: string | number
    weekday_average: string | number
    z_score: number
}

export const spikeAlertsSceneLogic = kea<spikeAlertsSceneLogicType>([
    path(['scenes', 'health', 'spikeAlerts', 'spikeAlertsSceneLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setSearchTerm: (term: string) => ({ term }),
    }),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }: { term: string }) => term,
            },
        ],
    }),
    loaders(() => ({
        spikeAlerts: [
            null as SpikeAlertsResponse | null,
            {
                loadSpikeAlerts: async (): Promise<SpikeAlertsResponse> => {
                    if (new URLSearchParams(window.location.search).get('mock') === 'true') {
                        const { MOCK_SPIKE_ALERTS } = await import('./spikeAlertsMock')
                        return MOCK_SPIKE_ALERTS
                    }
                    return await api.get('api/environments/@current/spike_alerts/')
                },
            },
        ],
    })),
    selectors({
        flatAlerts: [
            (s) => [s.spikeAlerts],
            (response: SpikeAlertsResponse | null): FlatSpikeRow[] =>
                (response?.results ?? []).flatMap((alert) =>
                    alert.detected_spikes.map((spike) => ({
                        rowKey: `${alert.id}-${spike.usage_key}`,
                        spike_date: alert.spike_date,
                        detected_at: alert.detected_at,
                        usage_key: spike.usage_key,
                        value: spike.value,
                        weekday_average: spike.weekday_average,
                        z_score: spike.z_score,
                    }))
                ),
        ],
        filteredAlerts: [
            (s) => [s.flatAlerts, s.searchTerm],
            (flatAlerts: FlatSpikeRow[], searchTerm: string): FlatSpikeRow[] => {
                if (!searchTerm.trim()) {
                    return flatAlerts
                }
                const lower = searchTerm.toLowerCase()
                return flatAlerts.filter((row) => row.usage_key.toLowerCase().includes(lower))
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Health,
                    name: sceneConfigurations[Scene.Health].name,
                    path: urls.health(),
                },
                {
                    key: Scene.SpikeAlerts,
                    name: 'Spike alerts',
                },
            ],
        ],
    }),
    afterMount(({ actions, values }) => {
        if (!values.featureFlags[FEATURE_FLAGS.SPIKE_ALERTS_PAGE]) {
            router.actions.replace(urls.health())
            return
        }
        actions.loadSpikeAlerts()
    }),
])
