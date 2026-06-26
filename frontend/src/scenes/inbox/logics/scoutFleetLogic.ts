import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/posthog_ai/frontend/types/taskTypes'
import { signalsScoutMetadataGet } from 'products/signals/frontend/generated/api'
import type { ScoutMetadataApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalScoutConfig, SignalScoutConfigUpdate, SignalScoutRunSummary } from '../types'
import {
    computeFleetSummary,
    computeScoutRollups,
    FleetSummary,
    getScoutOrigin,
    SCOUT_RUNS_WINDOW_HOURS,
    ScoutRollup,
    sortConfigsForDisplay,
} from '../utils/scoutRunsWindow'
import type { scoutFleetLogicType } from './scoutFleetLogicType'

// Fleet runs are refetched on a slow cadence so "running now" / recent emissions
// stay live without hammering the capped runs endpoint (desktop: 60s).
const RUNS_REFETCH_INTERVAL_MS = 60_000
// The runs endpoint caps each page at 100 rows newest-first. To cover the whole
// window we walk back page-by-page via a `date_to` cursor (the oldest run's
// `started_at`, as the backend documents). MAX_RUNS_PAGES bounds the walk so a
// pathologically busy fleet can't spin forever — hitting it flags the window truncated.
const RUNS_PAGE_LIMIT = 100
const MAX_RUNS_PAGES = 15

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
        // Started/stopped by the fleet-list component so the always-mounted setup widget
        // (which only reads configs) doesn't trigger the paginated runs-window polling.
        startRunsPolling: true,
        stopRunsPolling: true,
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
        scoutMetadata: [
            null as ScoutMetadataApi | null,
            {
                loadScoutMetadata: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    try {
                        return await signalsScoutMetadataGet(String(teamId))
                    } catch {
                        // The metadata feeds only the optional alpha banner, so a transient
                        // backend blip should degrade silently rather than surface a hard error.
                        return null
                    }
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
                    // Walk the full window newest→oldest, paginating via a `date_to` cursor so
                    // every scout shows its real run history (not just the fleet-wide newest 100).
                    const windowStart = dayjs().subtract(SCOUT_RUNS_WINDOW_HOURS, 'hours').toISOString()
                    const seen = new Set<string>()
                    const runs: SignalScoutRunSummary[] = []
                    let cursor: string | undefined
                    let complete = false

                    for (let page = 0; page < MAX_RUNS_PAGES; page++) {
                        const pageRuns = await api.signalScout.runs.list({
                            limit: RUNS_PAGE_LIMIT,
                            date_from: windowStart,
                            date_to: cursor,
                        })
                        for (const run of pageRuns) {
                            // `date_to` is exclusive, so a boundary row can reappear on the next
                            // page — dedupe by run_id to be safe.
                            if (!seen.has(run.run_id)) {
                                seen.add(run.run_id)
                                runs.push(run)
                            }
                        }
                        // A short page means we reached the start of the window — nothing older left.
                        if (pageRuns.length < RUNS_PAGE_LIMIT) {
                            complete = true
                            break
                        }
                        // Cursor on `created_at` — the exact field the endpoint filters/orders on, so
                        // the walk can't skip runs (`started_at` is the TaskRun's time and can differ).
                        const oldest = pageRuns[pageRuns.length - 1]
                        // No usable cursor, or the cursor can't advance (a full page of identical
                        // timestamps): stop, but the page was full so the window is NOT complete.
                        if (!oldest.created_at || oldest.created_at === cursor) {
                            break
                        }
                        cursor = oldest.created_at
                    }

                    return { runs, complete }
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
        // Flips true the first time the runs window loads *successfully* and stays true across the
        // 60s polls. Consumers (e.g. the scout detail Signals section) use it to tell "not loaded
        // yet" from "loaded, genuinely empty" without flickering a skeleton on polls. Deliberately
        // NOT set on failure: a failed first load must keep showing loading (the poll retries),
        // not latch and let a consumer render a false "no signals" empty state over no data.
        runsWindowLoadedOnce: [
            false,
            {
                loadRunsWindowSuccess: () => true,
            },
        ],
    }),

    selectors({
        // Editorial alpha/announcement banner from the signals-scout flag, or null when unset.
        scoutBannerMessage: [
            (s) => [s.scoutMetadata],
            (scoutMetadata): string | null => scoutMetadata?.banner_message ?? null,
        ],
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

    listeners(({ actions, values, cache }) => ({
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
        startRunsPolling: () => {
            // Fetch once immediately, then a slow poll keeps "running now" + recent emissions
            // fresh. The keyed disposable replaces any prior poll and is torn down on
            // stopRunsPolling / unmount / tab hide.
            actions.loadRunsWindow()
            cache.disposables.add(() => {
                const interval = setInterval(() => actions.loadRunsWindow(), RUNS_REFETCH_INTERVAL_MS)
                return () => clearInterval(interval)
            }, 'runsPoll')
        },
        stopRunsPolling: () => {
            cache.disposables.dispose('runsPoll')
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            // Configs are cheap and the always-mounted setup widget needs them. The paginated
            // runs window is loaded + polled only while the fleet list is open (startRunsPolling).
            actions.loadScoutConfigs()
            // Metadata carries the alpha banner; a one-shot read is enough (it changes rarely).
            actions.loadScoutMetadata()
        },
    })),
])
