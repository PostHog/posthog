import { MakeLogicType, actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { DataQualitySubjectRef, apiErrorDetail, checksApi } from 'products/data_quality/frontend/checksApi'
import {
    dataQualityChecksHealthList,
    dataQualityChecksList,
    dataQualityRunsCreate,
    dataQualityRunsRetrieve,
} from 'products/data_quality/frontend/generated/api'
import type {
    DataQualityCheckRunApi,
    DataQualityOverviewCheckApi,
    DataQualitySubjectHealthApi,
    DataQualitySuiteRunApi,
} from 'products/data_quality/frontend/generated/api.schemas'
import { openFailingRowsInSqlEditor } from 'products/data_quality/frontend/openFailingRows'
import {
    isTerminalSuiteRun,
    suiteRunOutcome,
    suiteRunPollListeners,
    suiteRunSummary,
} from 'products/data_quality/frontend/suiteRuns'

const CHECKS_LIMIT = 500

export type OverviewStatusFilter = 'all' | 'failing' | 'never_run'

export interface OverviewFilters {
    search: string
    status: OverviewStatusFilter
}

export const DEFAULT_OVERVIEW_FILTERS: OverviewFilters = { search: '', status: 'all' }

/** Checks and rollups from one refresh, committed together so rows and health always agree. */
export interface OverviewSnapshot {
    checks: DataQualityOverviewCheckApi[]
    health: DataQualitySubjectHealthApi[]
}

/** What a run is reporting into: the page, or exactly one subject panel. */
export type OverviewRunTarget = { kind: 'all' } | { kind: 'subject'; subjectKey: string }

/** One table or view, with the checks on it and its rollup. What the overview renders a section per. */
export interface SubjectGroup {
    /** Composite: a table and a view can hold the same uuid, and do collide in practice. */
    subjectKey: string
    subjectType: string
    subjectUuid: string
    subjectName: string
    detailUrl: string | null
    checks: DataQualityOverviewCheckApi[]
    health: string
    checksFailing: number
    // Denominator of the failing ratio. From the subject's rollup, not checks.length, since a filter
    // shows only a subset of the subject's checks and would otherwise read as "2 of 1 failing".
    checksTotal: number
}

// Worst first: someone opening this is looking for what is broken, not for an alphabet.
const HEALTH_ORDER: Record<string, number> = { failing: 0, erroring: 1, warn: 2, healthy: 3, unknown: 4 }

const UNHEALTHY = ['failing', 'erroring', 'warn']

export function subjectKeyOf(subjectType: string, subjectUuid: string | null | undefined): string {
    return `${subjectType}:${subjectUuid ?? ''}`
}

function subjectRefOf(check: DataQualityOverviewCheckApi): DataQualitySubjectRef {
    return { subjectType: check.subject_type, subjectId: check.subject_uuid ?? '' }
}

/** Where the subject's own page lives, or null when it has none and the name renders as text. */
export function subjectDetailUrl(check: DataQualityOverviewCheckApi): string | null {
    if (check.subject_type === 'view') {
        return check.subject_node_id ? urls.nodeDetail(check.subject_node_id, 'tests') : null
    }
    if (check.subject_source_id && check.subject_schema_id) {
        return urls.dataWarehouseSourceSchema(check.subject_source_id, check.subject_schema_id)
    }
    // A table linked by hand rather than synced has no source schema to sit under; its own id is
    // the route.
    return check.subject_uuid ? urls.dataWarehouseSource(`self-managed-${check.subject_uuid}`) : null
}

export const ROW_ACTIONS_ID_PREFIX = 'data-quality-check-actions-'
export const SUBJECT_DISCLOSURE_ID_PREFIX = 'data-quality-subject-disclosure-'
export const BROWSE_ACTION_ID = 'data-quality-browse-subjects'

export function rowActionsId(checkId: string): string {
    return `${ROW_ACTIONS_ID_PREFIX}${checkId}`
}

export function subjectDisclosureId(subjectKey: string): string {
    return `${SUBJECT_DISCLOSURE_ID_PREFIX}${subjectKey}`
}

/**
 * Where focus goes once a deleted row takes its own trigger with it, best first.
 *
 * Computed against the groups as they were before the row went, since that is the order the user
 * was looking at.
 */
export function focusCandidatesAfterDelete(groups: SubjectGroup[], subjectKey: string, checkId: string): string[] {
    const groupIndex = groups.findIndex((group) => group.subjectKey === subjectKey)
    const group = groups[groupIndex]
    const checkIndex = group?.checks.findIndex((check) => check.id === checkId) ?? -1
    const siblings = (group?.checks ?? []).filter((check) => check.id !== checkId)
    const next = checkIndex >= 0 ? siblings[checkIndex] : undefined
    const previous = checkIndex > 0 ? siblings[checkIndex - 1] : undefined

    return [
        ...(next ? [rowActionsId(next.id)] : []),
        ...(previous ? [rowActionsId(previous.id)] : []),
        ...(siblings.length ? [subjectDisclosureId(subjectKey)] : []),
        ...(groups[groupIndex + 1] ? [subjectDisclosureId(groups[groupIndex + 1].subjectKey)] : []),
        ...(groupIndex > 0 ? [subjectDisclosureId(groups[groupIndex - 1].subjectKey)] : []),
        BROWSE_ACTION_ID,
    ]
}

function projectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityOverviewLogicValues {
    activeSuiteRun: DataQualitySuiteRunApi | null
    allSubjectKeys: string[]
    checkRunsByCheckId: Record<string, DataQualityCheckRunApi[]>
    checks: DataQualityOverviewCheckApi[]
    deletingCheckIds: Record<string, boolean>
    expandedSubjectKeys: string[]
    expansionInitialized: boolean
    failingCheckCount: number
    failingSubjectCount: number
    filteredChecks: DataQualityOverviewCheckApi[]
    filters: OverviewFilters
    filtersActive: boolean
    healthBySubjectKey: {
        [k: string]: DataQualitySubjectHealthApi
    }
    isRunning: boolean
    lastActionCheckId: string | null
    overview: OverviewSnapshot | null
    overviewError: string | null
    overviewLoading: boolean
    overviewSummary: string | null
    pollTimedOut: boolean
    runError: string | null
    runTarget: OverviewRunTarget | null
    runningSubjectKey: string | null
    runsLoadingByCheckId: Record<string, boolean>
    snapshotLoaded: boolean
    startingRun: boolean
    subjectGroups: SubjectGroup[]
    subjectHealth: DataQualitySubjectHealthApi[]
    unhealthySubjectKeys: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityOverviewLogicActions {
    deleteCheck: (check: DataQualityOverviewCheckApi) => {
        check: DataQualityOverviewCheckApi
    }
    finishSuiteRun: (suiteRun: DataQualitySuiteRunApi) => {
        suiteRun: DataQualitySuiteRunApi
    }
    loadCheckRuns: (check: DataQualityOverviewCheckApi) => {
        check: DataQualityOverviewCheckApi
    }
    loadOverview: () => any
    loadOverviewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOverviewSuccess: (
        overview: {
            checks: DataQualityOverviewCheckApi[]
            health: DataQualitySubjectHealthApi[]
        },
        payload?: any
    ) => {
        overview: {
            checks: DataQualityOverviewCheckApi[]
            health: DataQualitySubjectHealthApi[]
        }
        payload?: any
    }
    openFailingRows: (check: DataQualityOverviewCheckApi) => {
        check: DataQualityOverviewCheckApi
    }
    pollActiveSuiteRun: () => {
        value: true
    }
    removeCheck: (checkId: string) => {
        checkId: string
    }
    runChecks: (
        target: OverviewRunTarget,
        checkIds?: string[]
    ) => {
        checkIds: string[]
        target: OverviewRunTarget
    }
    scheduleSuiteRunPoll: () => {
        value: true
    }
    setActiveSuiteRun: (suiteRun: DataQualitySuiteRunApi | null) => {
        suiteRun: DataQualitySuiteRunApi | null
    }
    setCheckDeleting: (
        checkId: string,
        deleting: boolean
    ) => {
        checkId: string
        deleting: boolean
    }
    setCheckRuns: (
        checkId: string,
        runs: DataQualityCheckRunApi[]
    ) => {
        checkId: string
        runs: DataQualityCheckRunApi[]
    }
    setExpandedSubjects: (subjectKeys: string[]) => {
        subjectKeys: string[]
    }
    setFilters: (filters: Partial<OverviewFilters>) => {
        filters: Partial<OverviewFilters>
    }
    setLastActionCheck: (checkId: string | null) => {
        checkId: string | null
    }
    setPollTimedOut: () => {
        value: true
    }
    setRunError: (error: string | null) => {
        error: string | null
    }
    setRunsLoading: (
        checkId: string,
        loading: boolean
    ) => {
        checkId: string
        loading: boolean
    }
    setStartingRun: (starting: boolean) => {
        starting: boolean
    }
    toggleSubjectExpanded: (subjectKey: string) => {
        subjectKey: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityOverviewLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        checks: (overview: OverviewSnapshot | null) => DataQualityOverviewCheckApi[]
        subjectHealth: (overview: OverviewSnapshot | null) => DataQualitySubjectHealthApi[]
        healthBySubjectKey: (subjectHealth: DataQualitySubjectHealthApi[]) => {
            [k: string]: DataQualitySubjectHealthApi
        }
        isRunning: (activeSuiteRun: DataQualitySuiteRunApi | null, pollTimedOut: boolean) => boolean
        runningSubjectKey: (
            runTarget: OverviewRunTarget | null,
            isRunning: boolean,
            startingRun: boolean
        ) => string | null
        filtersActive: (filters: OverviewFilters) => boolean
        filteredChecks: (
            checks: DataQualityOverviewCheckApi[],
            filters: OverviewFilters
        ) => DataQualityOverviewCheckApi[]
        failingCheckCount: (checks: DataQualityOverviewCheckApi[]) => number
        failingSubjectCount: (checks: DataQualityOverviewCheckApi[]) => number
        overviewSummary: (
            checks: DataQualityOverviewCheckApi[],
            failingCheckCount: number,
            failingSubjectCount: number
        ) => string | null
        subjectGroups: (
            filteredChecks: DataQualityOverviewCheckApi[],
            healthBySubjectKey: {
                [k: string]: DataQualitySubjectHealthApi
            }
        ) => SubjectGroup[]
        allSubjectKeys: (checks: DataQualityOverviewCheckApi[]) => string[]
        unhealthySubjectKeys: (subjectGroups: SubjectGroup[]) => string[]
    }
}

export type dataQualityOverviewLogicType = MakeLogicType<
    dataQualityOverviewLogicValues,
    dataQualityOverviewLogicActions,
    Record<string, any>,
    dataQualityOverviewLogicMeta
>

export const dataQualityOverviewLogic = kea<dataQualityOverviewLogicType>([
    path(['products', 'data_quality', 'frontend', 'overview', 'dataQualityOverviewLogic']),
    actions({
        setFilters: (filters: Partial<OverviewFilters>) => ({ filters }),
        toggleSubjectExpanded: (subjectKey: string) => ({ subjectKey }),
        setExpandedSubjects: (subjectKeys: string[]) => ({ subjectKeys }),
        loadCheckRuns: (check: DataQualityOverviewCheckApi) => ({ check }),
        openFailingRows: (check: DataQualityOverviewCheckApi) => ({ check }),
        setCheckRuns: (checkId: string, runs: DataQualityCheckRunApi[]) => ({ checkId, runs }),
        setRunsLoading: (checkId: string, loading: boolean) => ({ checkId, loading }),
        runChecks: (target: OverviewRunTarget, checkIds: string[] = []) => ({ target, checkIds }),
        setStartingRun: (starting: boolean) => ({ starting }),
        setActiveSuiteRun: (suiteRun: DataQualitySuiteRunApi | null) => ({ suiteRun }),
        scheduleSuiteRunPoll: true,
        pollActiveSuiteRun: true,
        finishSuiteRun: (suiteRun: DataQualitySuiteRunApi) => ({ suiteRun }),
        setPollTimedOut: true,
        deleteCheck: (check: DataQualityOverviewCheckApi) => ({ check }),
        setCheckDeleting: (checkId: string, deleting: boolean) => ({ checkId, deleting }),
        removeCheck: (checkId: string) => ({ checkId }),
        setLastActionCheck: (checkId: string | null) => ({ checkId }),
        setRunError: (error: string | null) => ({ error }),
    }),
    loaders(() => ({
        overview: [
            null as OverviewSnapshot | null,
            {
                // Fetched in parallel but committed as one value: rows and rollups that disagree
                // read as a bug, so a half-refresh keeps the last snapshot the user already has.
                loadOverview: async () => {
                    const [checks, health] = await Promise.all([
                        dataQualityChecksList(projectId(), { limit: CHECKS_LIMIT }),
                        dataQualityChecksHealthList(projectId()),
                    ])
                    return { checks: checks.results, health }
                },
            },
        ],
    })),
    reducers({
        filters: [
            DEFAULT_OVERVIEW_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        overview: {
            removeCheck: (state: OverviewSnapshot | null, { checkId }: { checkId: string }) =>
                state ? { ...state, checks: state.checks.filter((check) => check.id !== checkId) } : state,
        },
        snapshotLoaded: [
            false,
            {
                loadOverviewSuccess: () => true,
            },
        ],
        overviewError: [
            null as string | null,
            {
                loadOverview: () => null,
                loadOverviewSuccess: () => null,
                loadOverviewFailure: (_, { error }) => error || 'Failed to load',
            },
        ],
        expandedSubjectKeys: [
            [] as string[],
            {
                setExpandedSubjects: (_, { subjectKeys }) => subjectKeys,
                toggleSubjectExpanded: (state, { subjectKey }) =>
                    state.includes(subjectKey) ? state.filter((key) => key !== subjectKey) : [...state, subjectKey],
            },
        ],
        expansionInitialized: [
            false,
            {
                setExpandedSubjects: () => true,
            },
        ],
        startingRun: [
            false,
            {
                runChecks: () => true,
                setStartingRun: (_, { starting }) => starting,
            },
        ],
        runTarget: [
            null as OverviewRunTarget | null,
            {
                runChecks: (_, { target }) => target,
            },
        ],
        runError: [
            null as string | null,
            {
                runChecks: () => null,
                setRunError: (_, { error }) => error,
                setActiveSuiteRun: () => null,
            },
        ],
        activeSuiteRun: [
            null as DataQualitySuiteRunApi | null,
            {
                setActiveSuiteRun: (_, { suiteRun }) => suiteRun,
                finishSuiteRun: (_, { suiteRun }) => suiteRun,
            },
        ],
        pollTimedOut: [
            false,
            {
                setPollTimedOut: () => true,
                setActiveSuiteRun: () => false,
            },
        ],
        checkRunsByCheckId: [
            {} as Record<string, DataQualityCheckRunApi[]>,
            {
                setCheckRuns: (state, { checkId, runs }) => ({ ...state, [checkId]: runs }),
            },
        ],
        runsLoadingByCheckId: [
            {} as Record<string, boolean>,
            {
                setRunsLoading: (state, { checkId, loading }) => ({ ...state, [checkId]: loading }),
            },
        ],
        deletingCheckIds: [
            {} as Record<string, boolean>,
            {
                setCheckDeleting: (state, { checkId, deleting }) => ({ ...state, [checkId]: deleting }),
            },
        ],
        lastActionCheckId: [
            null as string | null,
            {
                setLastActionCheck: (_, { checkId }) => checkId,
            },
        ],
    }),
    selectors({
        checks: [(s) => [s.overview], (overview: OverviewSnapshot | null) => overview?.checks ?? []],
        subjectHealth: [(s) => [s.overview], (overview: OverviewSnapshot | null) => overview?.health ?? []],
        healthBySubjectKey: [
            (s) => [s.subjectHealth],
            (subjectHealth: DataQualitySubjectHealthApi[]) =>
                Object.fromEntries(
                    subjectHealth.map((entry) => [subjectKeyOf(entry.subject_type, entry.subject_uuid), entry])
                ),
        ],
        isRunning: [
            (s) => [s.activeSuiteRun, s.pollTimedOut],
            (activeSuiteRun: DataQualitySuiteRunApi | null, pollTimedOut: boolean) =>
                !!activeSuiteRun && !isTerminalSuiteRun(activeSuiteRun) && !pollTimedOut,
        ],
        runningSubjectKey: [
            (s) => [s.runTarget, s.isRunning, s.startingRun],
            (runTarget: OverviewRunTarget | null, isRunning: boolean, startingRun: boolean) =>
                (isRunning || startingRun) && runTarget?.kind === 'subject' ? runTarget.subjectKey : null,
        ],
        filtersActive: [
            (s) => [s.filters],
            (filters: OverviewFilters) => !!filters.search.trim() || filters.status !== 'all',
        ],
        filteredChecks: [
            (s) => [s.checks, s.filters],
            (checks: DataQualityOverviewCheckApi[], filters: OverviewFilters) => {
                const search = filters.search.trim().toLowerCase()
                return checks.filter((check) => {
                    if (filters.status === 'failing' && !['failed', 'errored'].includes(check.last_status ?? '')) {
                        return false
                    }
                    if (filters.status === 'never_run' && check.last_status) {
                        return false
                    }
                    if (!search) {
                        return true
                    }
                    return [check.name, check.subject_name, check.check_type, check.column_name]
                        .filter(Boolean)
                        .some((field) => String(field).toLowerCase().includes(search))
                })
            },
        ],
        failingCheckCount: [
            (s) => [s.checks],
            (checks: DataQualityOverviewCheckApi[]) =>
                checks.filter((check) => ['failed', 'errored'].includes(check.last_status ?? '')).length,
        ],
        // Counted from the same checks as failingCheckCount, not the health rollup: a warn-severity
        // or disabled failure raises the check count but leaves the subject's health short of
        // 'failing', which would read as "N checks failing, across 0 tables and views".
        failingSubjectCount: [
            (s) => [s.checks],
            (checks: DataQualityOverviewCheckApi[]) =>
                new Set(
                    checks
                        .filter((check) => ['failed', 'errored'].includes(check.last_status ?? ''))
                        .map((check) => subjectKeyOf(check.subject_type, check.subject_uuid))
                ).size,
        ],
        // A not-failing check is not a passed check: a never-run or skipped one also has no failure.
        // Only claim every check passed when every check actually passed, so a fresh page of unrun
        // checks does not read as an all-clear.
        overviewSummary: [
            (s) => [s.checks, s.failingCheckCount, s.failingSubjectCount],
            (
                checks: DataQualityOverviewCheckApi[],
                failingCheckCount: number,
                failingSubjectCount: number
            ): string | null => {
                if (checks.length === 0) {
                    return null
                }
                if (failingCheckCount > 0) {
                    return `${failingCheckCount} of ${checks.length} checks failing, across ${failingSubjectCount} tables and views.`
                }
                const passed = checks.filter((check) => check.last_status === 'passed').length
                if (passed === checks.length) {
                    return `All ${checks.length} checks passed on their last run.`
                }
                if (passed === 0) {
                    return 'None of your checks have run yet.'
                }
                const notRun = checks.filter((check) => !check.last_status).length
                return `${passed} of ${checks.length} checks passed on their last run, ${notRun} not run yet.`
            },
        ],
        subjectGroups: [
            (s) => [s.filteredChecks, s.healthBySubjectKey],
            (
                filteredChecks: DataQualityOverviewCheckApi[],
                healthBySubjectKey: Record<string, DataQualitySubjectHealthApi>
            ): SubjectGroup[] => {
                const groups = new Map<string, SubjectGroup>()
                for (const check of filteredChecks) {
                    const subjectKey = subjectKeyOf(check.subject_type, check.subject_uuid)
                    const group = groups.get(subjectKey) ?? {
                        subjectKey,
                        subjectType: check.subject_type,
                        subjectUuid: check.subject_uuid ?? '',
                        subjectName: check.subject_name,
                        detailUrl: subjectDetailUrl(check),
                        checks: [],
                        health: healthBySubjectKey[subjectKey]?.health ?? 'unknown',
                        checksFailing: healthBySubjectKey[subjectKey]?.checks_failing ?? 0,
                        checksTotal: healthBySubjectKey[subjectKey]?.checks_total ?? 0,
                    }
                    group.checks.push(check)
                    groups.set(subjectKey, group)
                }
                return [...groups.values()].sort(
                    (left, right) =>
                        (HEALTH_ORDER[left.health] ?? 9) - (HEALTH_ORDER[right.health] ?? 9) ||
                        left.subjectName.localeCompare(right.subjectName)
                )
            },
        ],
        allSubjectKeys: [
            (s) => [s.checks],
            (checks: DataQualityOverviewCheckApi[]) => [
                ...new Set(checks.map((check) => subjectKeyOf(check.subject_type, check.subject_uuid))),
            ],
        ],
        // Someone opening this wants the broken ones open; healthy subjects stay collapsed.
        unhealthySubjectKeys: [
            (s) => [s.subjectGroups],
            (subjectGroups: SubjectGroup[]) =>
                subjectGroups.filter((group) => UNHEALTHY.includes(group.health)).map((group) => group.subjectKey),
        ],
    }),
    listeners(({ actions, values, cache }) => {
        // Assigned one by one rather than spread: kea-typegen walks this object literal and crashes
        // on a spread element, which has no property name.
        const poll = suiteRunPollListeners({
            retrieve: (suiteRunId) => dataQualityRunsRetrieve(projectId(), suiteRunId),
            cache,
            values,
            actions,
        })
        return {
            setActiveSuiteRun: poll.setActiveSuiteRun,
            scheduleSuiteRunPoll: poll.scheduleSuiteRunPoll,
            pollActiveSuiteRun: poll.pollActiveSuiteRun,
            loadOverviewSuccess: () => {
                if (!values.expansionInitialized) {
                    actions.setExpandedSubjects(values.unhealthySubjectKeys)
                    return
                }
                // Pruned against every subject, not the filtered ones, so a filter never collapses a
                // panel the user opened.
                const present = new Set(values.allSubjectKeys)
                const kept = values.expandedSubjectKeys.filter((key) => present.has(key))
                if (kept.length !== values.expandedSubjectKeys.length) {
                    actions.setExpandedSubjects(kept)
                }
            },
            loadCheckRuns: async ({ check }) => {
                if (values.runsLoadingByCheckId[check.id]) {
                    return
                }
                actions.setRunsLoading(check.id, true)
                try {
                    actions.setCheckRuns(check.id, await checksApi.runs(subjectRefOf(check), check.id))
                } catch (error) {
                    lemonToast.error(apiErrorDetail(error) ?? 'Could not load the run history. Try again.')
                } finally {
                    actions.setRunsLoading(check.id, false)
                }
            },
            openFailingRows: async ({ check }) => {
                await openFailingRowsInSqlEditor({
                    cachedRuns: values.checkRunsByCheckId[check.id],
                    fetchRuns: () => checksApi.runs(subjectRefOf(check), check.id),
                    onRunsFetched: (runs) => actions.setCheckRuns(check.id, runs),
                })
            },
            runChecks: async ({ checkIds }) => {
                try {
                    // An empty selection is the "everything" case, which the endpoint reads as no filter.
                    actions.setActiveSuiteRun(await dataQualityRunsCreate(projectId(), { check_ids: checkIds }))
                } catch (error) {
                    actions.setRunError(apiErrorDetail(error) ?? "Couldn't run checks.")
                } finally {
                    actions.setStartingRun(false)
                }
            },
            deleteCheck: async ({ check }) => {
                if (values.deletingCheckIds[check.id]) {
                    return
                }
                actions.setCheckDeleting(check.id, true)
                try {
                    await checksApi.destroy(
                        { subjectType: check.subject_type, subjectId: check.subject_uuid ?? '' },
                        check.id
                    )
                    actions.removeCheck(check.id)
                    actions.loadOverview()
                    lemonToast.success('Check deleted')
                } catch (error) {
                    lemonToast.error(apiErrorDetail(error) ?? 'Could not delete the check. Try again.')
                } finally {
                    actions.setCheckDeleting(check.id, false)
                }
            },
            finishSuiteRun: ({ suiteRun }) => {
                cache.disposables.dispose('suiteRunPoll')
                actions.loadOverview()
                // loadOverview refreshes status and rollups but not the runs cached under an expanded
                // row, so reload each; without this a row expanded before the run keeps showing the
                // pre-run history, and openFailingRows opens the stale query.
                const checksById = new Map(values.checks.map((check) => [check.id, check]))
                Object.keys(values.checkRunsByCheckId).forEach((checkId) => {
                    const check = checksById.get(checkId)
                    if (check) {
                        actions.loadCheckRuns(check)
                    }
                })
                const outcome = suiteRunOutcome(suiteRun)
                if (outcome === 'empty') {
                    lemonToast.info('No enabled checks to run')
                } else if (outcome === 'errored') {
                    // An inline banner rather than a toast: this page has a retry control for it.
                    actions.setRunError(suiteRun.error || "Couldn't run checks. Try again.")
                } else if (outcome === 'warning') {
                    lemonToast.warning(suiteRunSummary(suiteRun))
                } else {
                    lemonToast.success(suiteRunSummary(suiteRun))
                }
            },
        }
    }),
    afterMount(({ actions }) => {
        actions.loadOverview()
    }),
])
