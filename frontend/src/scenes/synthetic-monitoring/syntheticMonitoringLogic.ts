import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { syntheticMonitoringLogicType } from './syntheticMonitoringLogicType'
import { SyntheticMonitor, SyntheticMonitoringTab } from './types'

export const syntheticMonitoringLogic = kea<syntheticMonitoringLogicType>([
    path(['scenes', 'synthetic-monitoring', 'syntheticMonitoringLogic']),
    connect({
        values: [userLogic, ['user']],
    }),
    actions({
        setTab: (tab: SyntheticMonitoringTab) => ({ tab }),
        loadMonitors: true,
        deleteMonitor: (id: string) => ({ id }),
        pauseMonitor: (id: string) => ({ id }),
        resumeMonitor: (id: string) => ({ id }),
        testMonitor: (id: string) => ({ id }),
    }),
    loaders(({ values }) => ({
        monitors: [
            [] as SyntheticMonitor[],
            {
                loadMonitors: async () => {
                    const response = await api.syntheticMonitoring.list()
                    return response.results
                },
                deleteMonitor: async ({ id }) => {
                    await api.syntheticMonitoring.delete(id)
                    lemonToast.success('Monitor deleted successfully')
                    return values.monitors.filter((m) => m.id !== id)
                },
                pauseMonitor: async ({ id }) => {
                    const updated = await api.syntheticMonitoring.pause(id)
                    lemonToast.success('Monitor paused')
                    return values.monitors.map((m) => (m.id === id ? updated : m))
                },
                resumeMonitor: async ({ id }) => {
                    const updated = await api.syntheticMonitoring.resume(id)
                    lemonToast.success('Monitor resumed')
                    return values.monitors.map((m) => (m.id === id ? updated : m))
                },
            },
        ],
    })),
    reducers({
        tab: [
            SyntheticMonitoringTab.Monitors as SyntheticMonitoringTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        activeMonitors: [
            (s) => [s.monitors],
            (monitors): SyntheticMonitor[] => monitors.filter((m) => m.enabled),
        ],
        pausedMonitors: [
            (s) => [s.monitors],
            (monitors): SyntheticMonitor[] => monitors.filter((m) => !m.enabled),
        ],
        failingMonitors: [
            (s) => [s.monitors],
            (monitors): SyntheticMonitor[] =>
                monitors.filter((m) => m.state === 'failing' || m.state === 'error'),
        ],
    }),
    listeners(({ actions }) => ({
        testMonitor: async ({ id }) => {
            try {
                await api.syntheticMonitoring.test(id)
                lemonToast.success('Test check triggered')
            } catch (error) {
                lemonToast.error('Failed to trigger test check')
            }
        },
    })),
    urlToAction(({ actions }) => ({
        [urls.syntheticMonitoring()]: (_, searchParams) => {
            if (searchParams.tab) {
                actions.setTab(searchParams.tab as SyntheticMonitoringTab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMonitors()
    }),
])
