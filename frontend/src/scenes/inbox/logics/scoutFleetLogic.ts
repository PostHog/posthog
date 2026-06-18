import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/tasks/frontend/types'

import { SignalScoutConfig, SignalScoutConfigUpdate, SignalScoutRunSummary } from '../types'
import {
    computeFleetSummary,
    computeScoutRollups,
    FleetSummary,
    getScoutOrigin,
    ScoutRollup,
    sortConfigsForDisplay,
} from '../utils/scoutRunsWindow'
import type { scoutFleetLogicType } from './scoutFleetLogicType'

// Fleet runs are refetched on a slow cadence so "running now" / recent emissions
// stay live without hammering the capped runs endpoint (desktop: 60s).
const RUNS_REFETCH_INTERVAL_MS = 60_000
const RUNS_PAGE_LIMIT = 100

/**
 * Cloud port of desktop's scouts fleet hooks (`useScoutConfigs`, `useScoutRuns`,
 * `useScoutConfigMutations`, `useScoutChatTask`). Owns:
 * - loaders for scout configs + the recent runs window
 * - optimistic config mutations (enable/disable, live/dry-run, cadence)
 * - the runs-window rollups + fleet summary selectors
 * - "Make a scout" / fleet-overview / recent-signals chat task-kickoffs
 */
export const scoutFleetLogic = kea<scoutFleetLogicType>([
    path(['scenes', 'inbox', 'logics', 'scoutFleetLogic']),

    actions({
        updateScoutConfig: (configId: string, updates: SignalScoutConfigUpdate) => ({ configId, updates }),
        patchScoutConfigLocally: (configId: string, updates: SignalScoutConfigUpdate) => ({ configId, updates }),
        setHideDisabled: (hideDisabled: boolean) => ({ hideDisabled }),
        setExpanded: (expanded: boolean) => ({ expanded }),
        startScoutChatTask: (prompt: string, taskLabel: string, fallbackTitle: string) => ({
            prompt,
            taskLabel,
            fallbackTitle,
        }),
        startScoutChatTaskSuccess: true,
        startScoutChatTaskFailure: true,
    }),

    loaders(() => ({
        scoutConfigs: [
            null as SignalScoutConfig[] | null,
            {
                loadScoutConfigs: async () => {
                    return await api.signalScout.configs.list()
                },
            },
        ],
        runsWindow: [
            { runs: [] as SignalScoutRunSummary[], complete: true } as {
                runs: SignalScoutRunSummary[]
                complete: boolean
            },
            {
                loadRunsWindow: async () => {
                    const runs = await api.signalScout.runs.list({ limit: RUNS_PAGE_LIMIT })
                    // The endpoint caps at 100 rows; if it returned a full page there may be
                    // older runs in the window we can't see, so flag the window as truncated.
                    return { runs, complete: runs.length < RUNS_PAGE_LIMIT }
                },
            },
        ],
    })),

    reducers({
        // Tracks whether any chat-task kickoff is mid-flight (CTA disabled state).
        chatTaskRunning: [
            false,
            {
                startScoutChatTask: () => true,
                startScoutChatTaskSuccess: () => false,
                startScoutChatTaskFailure: () => false,
            },
        ],
        expanded: [
            // Defaults open: the only consumer is the Scout troop setup modal, which should
            // show the troop list immediately rather than a collapsed one-line pulse.
            true,
            {
                setExpanded: (_, { expanded }) => expanded,
            },
        ],
        hideDisabled: [
            false,
            {
                setHideDisabled: (_, { hideDisabled }) => hideDisabled,
            },
        ],
        scoutConfigs: [
            null as SignalScoutConfig[] | null,
            {
                // Optimistic patch; the listener reconciles against the server response.
                patchScoutConfigLocally: (state, { configId, updates }) =>
                    state?.map((config) => (config.id === configId ? { ...config, ...updates } : config)) ?? state,
            },
        ],
    }),

    selectors({
        rollups: [
            (s) => [s.runsWindow],
            (runsWindow): Map<string, ScoutRollup> => computeScoutRollups(runsWindow.runs),
        ],
        fleetSummary: [
            (s) => [s.scoutConfigs, s.rollups],
            (scoutConfigs, rollups): FleetSummary | null =>
                scoutConfigs ? computeFleetSummary(scoutConfigs, rollups) : null,
        ],
        enabledCount: [
            (s) => [s.scoutConfigs],
            (scoutConfigs): number => scoutConfigs?.filter((config) => config.enabled).length ?? 0,
        ],
        lastRunAt: [
            (s) => [s.scoutConfigs],
            (scoutConfigs): string | null => {
                let latest: string | null = null
                for (const config of scoutConfigs ?? []) {
                    if (config.last_run_at && (!latest || config.last_run_at > latest)) {
                        latest = config.last_run_at
                    }
                }
                return latest
            },
        ],
        visibleConfigs: [
            (s) => [s.scoutConfigs, s.hideDisabled],
            (scoutConfigs, hideDisabled): SignalScoutConfig[] => {
                const sorted = sortConfigsForDisplay(scoutConfigs ?? [])
                return hideDisabled ? sorted.filter((config) => config.enabled) : sorted
            },
        ],
        runsWindowComplete: [(s) => [s.runsWindow], (runsWindow): boolean => runsWindow.complete],
        customScoutCount: [
            (s) => [s.scoutConfigs],
            (scoutConfigs): number =>
                scoutConfigs?.filter((config) => getScoutOrigin(config.skill_name) === 'custom').length ?? 0,
        ],
    }),

    listeners(({ actions, values }) => ({
        updateScoutConfig: async ({ configId, updates }) => {
            const previousConfig = values.scoutConfigs?.find((config) => config.id === configId)
            // Optimistic update so the toggle/select feels instant.
            actions.patchScoutConfigLocally(configId, updates)
            try {
                const updated = await api.signalScout.configs.update(configId, updates)
                // Reconcile this one row against the server (preserves concurrent edits to others).
                actions.patchScoutConfigLocally(configId, updated)
            } catch (error: any) {
                if (previousConfig) {
                    actions.patchScoutConfigLocally(configId, previousConfig)
                }
                lemonToast.error(error?.detail || error?.message || 'Failed to update scout config')
            }
        },
        startScoutChatTask: async ({ prompt, fallbackTitle, taskLabel }) => {
            // Task-kickoff, mirroring inboxTaskKickoffLogic: create an auto-mode cloud
            // task from a templated prompt, then navigate to it. Not a live chat.
            try {
                let repository: string | undefined
                try {
                    const { repositories } = await api.tasks.repositories()
                    repository = repositories[0]
                } catch {
                    repository = undefined
                }
                const task = await api.tasks.create({
                    title: fallbackTitle,
                    description: prompt,
                    origin_product: OriginProduct.SIGNAL_REPORT,
                    repository,
                })
                actions.startScoutChatTaskSuccess()
                router.actions.push(urls.taskDetail(task.id))
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || `Failed to start ${taskLabel}`)
                actions.startScoutChatTaskFailure()
            }
        },
    })),

    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadScoutConfigs()
            actions.loadRunsWindow()
            // Slow poll keeps "running now" + recent emissions fresh. The keyed disposable
            // is torn down automatically on unmount / tab hide.
            cache.disposables.add(() => {
                const interval = setInterval(() => actions.loadRunsWindow(), RUNS_REFETCH_INTERVAL_MS)
                return () => clearInterval(interval)
            }, 'runsPoll')
        },
    })),
])
