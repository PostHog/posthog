import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/posthog_ai/frontend/types/taskTypes'
import { signalsScoutMetadataGet, signalsScoutRunsFindingsSummary } from 'products/signals/frontend/generated/api'
import type { FleetFindingsSummaryApi, ScoutMetadataApi } from 'products/signals/frontend/generated/api.schemas'
import { llmSkillsNameArchiveCreate } from 'products/skills/frontend/generated/api'

import { SignalScoutConfig, SignalScoutConfigUpdate, SignalScoutRunSummary } from '../types'
import {
    computeFleetSummary,
    computeScoutRollups,
    FleetSummary,
    prettifyScoutSkillName,
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
        deleteScout: (configId: string) => ({ configId }),
        deleteScoutFinished: (configId: string) => ({ configId }),
        removeScoutConfigLocally: (configId: string) => ({ configId }),
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
        // Cheap fleet-wide findings tally for the "Scout findings" callout — one backend query over
        // emitted runs, so the callout no longer waits on the full paginated runs-window walk (which
        // could take ~10s and was the reason the callout appeared long after the modal opened).
        fleetFindingsSummary: [
            null as FleetFindingsSummaryApi | null,
            {
                loadFleetFindingsSummary: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await signalsScoutRunsFindingsSummary(String(teamId))
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
        // Tracks which CTA's chat-task kickoff is mid-flight, keyed by its prompt, so only the
        // pressed chip spins (the others merely disable). A shared boolean spun all three at once.
        runningChatPrompt: [
            null as string | null,
            {
                startScoutChatTask: (_, { prompt }) => prompt,
                startScoutChatTaskSuccess: () => null,
                startScoutChatTaskFailure: () => null,
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
                // Drop a deleted row from the list once the backend confirms removal.
                removeScoutConfigLocally: (state, { configId }) =>
                    state?.filter((config) => config.id !== configId) ?? state,
            },
        ],
        // Scouts with a delete request in flight — drives the delete button's loading/disabled state
        // so a slow request can't be submitted twice from the still-visible row.
        deletingScoutIds: [
            [] as string[],
            {
                deleteScout: (state, { configId }) => (state.includes(configId) ? state : [...state, configId]),
                deleteScoutFinished: (state, { configId }) => state.filter((id) => id !== configId),
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
        // Flips true once the cheap findings summary lands, so the callout can tell "not loaded yet"
        // from "loaded, genuinely zero" without the full runs window. Like `runsWindowLoadedOnce`,
        // deliberately NOT set on failure: a failed load keeps the callout hidden, not falsely empty.
        fleetFindingsSummaryLoadedOnce: [
            false,
            {
                loadFleetFindingsSummarySuccess: () => true,
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
        // Fleet-wide findings tally for the "Scout findings" callout, read from the cheap backend
        // summary rather than the paginated runs window. The backend counts the same capped set the
        // findings page renders (most recent 120 emitted runs in the window), so the callout can't
        // over-advertise. Zeroed until the summary loads.
        emittedFindingsSummary: [
            (s) => [s.fleetFindingsSummary],
            (
                fleetFindingsSummary: FleetFindingsSummaryApi | null
            ): { count: number; scoutCount: number; latestAt: string | null } => ({
                count: fleetFindingsSummary?.count ?? 0,
                scoutCount: fleetFindingsSummary?.scout_count ?? 0,
                latestAt: fleetFindingsSummary?.latest_at ?? null,
            }),
        ],
        customScoutCount: [
            (s) => [s.scoutConfigs],
            (scoutConfigs): number => scoutConfigs?.filter((config) => config.scout_origin === 'custom').length ?? 0,
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
        deleteScout: async ({ configId }) => {
            // The reducer above already flags this id, but that value is reactive (for the button)
            // and can't tell a fresh submit from a duplicate. The cache Set is the non-reactive guard:
            // a second submit while the first is in flight bails before issuing another request.
            const inFlight: Set<string> = (cache.deletingScoutIds ??= new Set())
            if (inFlight.has(configId)) {
                return
            }
            inFlight.add(configId)
            try {
                const config = values.scoutConfigs?.find((c) => c.id === configId)
                if (!config) {
                    return
                }
                const displayName = prettifyScoutSkillName(config.skill_name)
                // Scout skills are seeded under the canonical (parent/root) team, and the coordinator's
                // `register_missing_configs` only scans skill rows there — so archive against the canonical
                // project id, not the raw child-environment team id. Archiving the child team would 404 (the
                // skill lives on the parent), get swallowed as "already archived" below, and leave a live
                // skill the coordinator re-seeds. `currentProjectId` mirrors the backend `_canonical_team_id`
                // (parent_team_id or team_id); it's '@current' until the team loads, which we reject.
                const canonicalProjectId = teamLogic.values.currentProjectId
                try {
                    // Archiving the skill is the permanent off switch: the coordinator won't re-seed a
                    // tombstoned skill or re-create its config. Only custom scouts are deletable — the UI
                    // offers canonical ones disable instead, since a deleted canonical scout can't be re-added.
                    if (config.scout_origin === 'custom') {
                        // A custom scout's config must never be dropped without first archiving its skill —
                        // otherwise the coordinator re-seeds the config and the scout runs again. If the
                        // project can't be resolved to archive, fail here instead of half-deleting (the outer
                        // catch surfaces the error and reloads, leaving the row intact).
                        if (typeof canonicalProjectId !== 'number') {
                            throw new Error('Could not resolve the active project to archive the scout')
                        }
                        try {
                            await llmSkillsNameArchiveCreate(String(canonicalProjectId), config.skill_name)
                        } catch (error: any) {
                            // Already archived (e.g. retrying after a partial failure) — fall through to
                            // clear the leftover config rather than dead-ending on a 404.
                            if (error?.status !== 404) {
                                throw error
                            }
                        }
                    }
                    await api.signalScout.configs.delete(configId)
                    // Remove only after the backend confirms — deletion is irreversible, so no optimistic
                    // drop that would have to be re-inserted (and re-sorted) on failure.
                    actions.removeScoutConfigLocally(configId)
                    lemonToast.success(`Deleted ${displayName}`)
                } catch (error: any) {
                    lemonToast.error(error?.detail || error?.message || 'Failed to delete scout')
                    // A partial failure (skill archived but config delete failed) could desync the list
                    // from the backend — reload the truth so the row reflects reality.
                    actions.loadScoutConfigs()
                }
            } finally {
                inFlight.delete(configId)
                actions.deleteScoutFinished(configId)
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
            // stopRunsPolling / unmount / tab hide. The cheap findings summary rides the same
            // cadence so the "Scout findings" callout fills in on its own fast query rather than
            // waiting on the paginated runs-window walk.
            actions.loadRunsWindow()
            actions.loadFleetFindingsSummary()
            cache.disposables.add(() => {
                const interval = setInterval(() => {
                    actions.loadRunsWindow()
                    actions.loadFleetFindingsSummary()
                }, RUNS_REFETCH_INTERVAL_MS)
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
