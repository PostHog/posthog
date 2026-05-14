import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { deploymentLogsLogicType } from './deploymentLogsLogicType'
import { DeploymentStatus, DeploymentStatusEnumApi } from './fixtures'
import { deploymentProjectsDeploymentsLogsRetrieve } from './generated/api'
import type { DeploymentLogEntryApi, DeploymentLogsResponseApi } from './generated/api.schemas'

export const NON_TERMINAL_STATUSES: ReadonlySet<DeploymentStatus> = new Set<DeploymentStatus>([
    DeploymentStatusEnumApi.Queued,
    DeploymentStatusEnumApi.Initializing,
    DeploymentStatusEnumApi.Building,
])

export const LOG_POLL_INTERVAL_MS = 3000
export const SEARCH_DEBOUNCE_MS = 300

export const isNonTerminal = (status: DeploymentStatus | null | undefined): boolean =>
    !!status && NON_TERMINAL_STATUSES.has(status)

export interface DeploymentLogsLogicProps {
    projectId: string
    deploymentId: string
    status: DeploymentStatus
}

export const deploymentLogsLogic = kea<deploymentLogsLogicType>([
    props({} as DeploymentLogsLogicProps),
    key((p) => `${p.projectId}/${p.deploymentId}`),
    path((key) => ['products', 'deployments', 'frontend', 'deploymentLogsLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        toggleLevelFilter: (level: string) => ({ level }),
        toggleStepFilter: (step: string) => ({ step }),
        clearFilters: true,
        setSearch: (search: string) => ({ search }),
        setFollowTail: (followTail: boolean) => ({ followTail }),
        markLogsFetched: true,
        // Internal: schedules a delayed re-fetch via the disposables plugin.
        // Pulled out as an action so propsChanged() can clear it without a
        // direct cache reference.
        schedulePoll: true,
        cancelPoll: true,
    }),
    reducers({
        levelFilters: [
            new Set<string>() as ReadonlySet<string>,
            {
                toggleLevelFilter: (state, { level }) => {
                    const next = new Set(state)
                    if (next.has(level)) {
                        next.delete(level)
                    } else {
                        next.add(level)
                    }
                    return next
                },
                clearFilters: () => new Set<string>(),
            },
        ],
        stepFilters: [
            new Set<string>() as ReadonlySet<string>,
            {
                toggleStepFilter: (state, { step }) => {
                    const next = new Set(state)
                    if (next.has(step)) {
                        next.delete(step)
                    } else {
                        next.add(step)
                    }
                    return next
                },
                clearFilters: () => new Set<string>(),
            },
        ],
        search: [
            '' as string,
            {
                setSearch: (_, { search }) => search,
                clearFilters: () => '',
            },
        ],
        // null = "use the default for this status" so we can change the
        // status without overwriting an explicit user choice.
        followTailOverride: [
            null as boolean | null,
            {
                setFollowTail: (_, { followTail }) => followTail,
            },
        ],
        lastFetchedAt: [
            null as number | null,
            {
                markLogsFetched: () => Date.now(),
            },
        ],
        logsError: [
            false,
            {
                loadLogs: () => false,
                loadLogsSuccess: () => false,
                loadLogsFailure: () => true,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        logsResponse: [
            null as DeploymentLogsResponseApi | null,
            {
                loadLogs: async (_: void, breakpoint): Promise<DeploymentLogsResponseApi | null> => {
                    const teamId = values.currentTeamId
                    // Cold-start guards:
                    //   * `teamId` null while teamLogic resolves on first paint.
                    //   * `props.deploymentId` / `props.projectId` can be undefined
                    //     during the scene-mount → URL-params-resolve race.
                    // Returning null signals "no fetch happened" to the success
                    // listener so we don't bump `lastFetchedAt` or kick the poll.
                    if (!teamId || !props.deploymentId || !props.projectId) {
                        return null
                    }
                    const response = await deploymentProjectsDeploymentsLogsRetrieve(
                        String(teamId),
                        props.projectId,
                        props.deploymentId
                    )
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    selectors(() => ({
        rawRows: [
            (s) => [s.logsResponse],
            (response: DeploymentLogsResponseApi | null): DeploymentLogEntryApi[] => response?.results ?? [],
        ],
        hasMore: [
            (s) => [s.logsResponse],
            (response: DeploymentLogsResponseApi | null): boolean => response?.has_more ?? false,
        ],
        rowLimit: [
            (s) => [s.logsResponse],
            (response: DeploymentLogsResponseApi | null): number => response?.row_limit ?? 1000,
        ],
        // Non-terminal deployments stream new lines, so the panel polls and
        // follow-tail defaults ON. Terminal sets are frozen — no polling, and
        // follow-tail defaults OFF so users can scroll through history.
        isLive: [() => [(_, p) => p.status], (status: DeploymentStatus): boolean => isNonTerminal(status)],
        followTail: [
            (s) => [s.followTailOverride, s.isLive],
            (override: boolean | null, isLive: boolean): boolean => (override === null ? isLive : override),
        ],
        filteredRows: [
            (s) => [s.rawRows, s.levelFilters, s.stepFilters, s.search],
            (
                rows: DeploymentLogEntryApi[],
                levelFilters: ReadonlySet<string>,
                stepFilters: ReadonlySet<string>,
                search: string
            ): DeploymentLogEntryApi[] => {
                const needle = search.trim().toLowerCase()
                return rows.filter((row) => {
                    if (levelFilters.size > 0 && row.level && !levelFilters.has(row.level)) {
                        return false
                    }
                    if (stepFilters.size > 0 && row.step && !stepFilters.has(row.step)) {
                        return false
                    }
                    if (needle && !(row.line ?? '').toLowerCase().includes(needle)) {
                        return false
                    }
                    return true
                })
            },
        ],
        hasActiveFilters: [
            (s) => [s.levelFilters, s.stepFilters, s.search],
            (l: ReadonlySet<string>, st: ReadonlySet<string>, search: string): boolean =>
                l.size > 0 || st.size > 0 || !!search.trim(),
        ],
        // Read directly from props so the selector recomputes when the parent
        // re-renders with a new status (propsChanged handles the lifecycle).
        status: [() => [(_, p) => p.status], (status: DeploymentStatus): DeploymentStatus => status],
    })),
    listeners(({ actions, values, cache }) => ({
        loadLogsSuccess: ({ logsResponse }) => {
            // The loader returns null when currentTeamId hasn't resolved yet
            // (cold start). Treat that as a no-op so we don't flip
            // lastFetchedAt to "now" and don't kick off the 3s poll loop.
            if (logsResponse === null) {
                return
            }
            actions.markLogsFetched()
            if (values.isLive) {
                actions.schedulePoll()
            }
        },
        loadLogsFailure: () => {
            actions.cancelPoll()
            lemonToast.error('Failed to load build logs — try again in a moment.')
        },
        setSearch: async (_, breakpoint) => {
            // Debounce search input so each keystroke doesn't re-run the
            // filter selector. The selector itself is pure-memoised, but the
            // debounce keeps re-renders cheap on long lists.
            await breakpoint(SEARCH_DEBOUNCE_MS)
        },
        schedulePoll: () => {
            cache.disposables.add(() => {
                const id = setTimeout(() => actions.loadLogs(), LOG_POLL_INTERVAL_MS)
                return () => clearTimeout(id)
            }, 'logsPoll')
        },
        cancelPoll: () => {
            cache.disposables.dispose('logsPoll')
        },
    })),
    propsChanged(({ actions, props, values }, oldProps) => {
        if (props.status === oldProps.status) {
            return
        }
        const wasLive = isNonTerminal(oldProps.status)
        const isLive = isNonTerminal(props.status)
        if (wasLive && !isLive) {
            // Transition into a terminal state — pick up any final lines the
            // worker emitted between the previous poll tick and the transition.
            actions.cancelPoll()
            actions.loadLogs()
        } else if (!wasLive && isLive) {
            // Shouldn't happen against the documented state machine, but the
            // guard avoids a stuck-paused panel if it ever does.
            if (!values.logsResponseLoading) {
                actions.schedulePoll()
            }
        }
    }),
    afterMount(({ actions }) => {
        actions.loadLogs()
    }),
])
