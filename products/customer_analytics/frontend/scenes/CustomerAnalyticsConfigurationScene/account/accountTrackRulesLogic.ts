import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    accountTrackRulesList,
    accountTrackRulesPreviewCreate,
    accountTrackRulesRunCreate,
    accountTrackRulesRunsList,
    accountTrackRulesUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountTrackRuleGroupApi,
    AccountTrackRulePreviewApi,
    AccountTrackRuleRunViewApi,
    AccountTrackRulesConfigApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

const RUN_POLL_INTERVAL_MS = 5_000
const RUN_POLL_MAX_ATTEMPTS = 360
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'stale'])

function captureUnexpectedApiError(error: unknown, scope: string): void {
    if (!(error instanceof ApiError) || (error.status ?? 500) >= 500) {
        posthog.captureException(error, { scope })
    }
}

const EMPTY_CONFIG: AccountTrackRulesConfigApi = {
    schema_version: 1,
    version: 0,
    enabled: false,
    groups: [],
}

export interface accountTrackRulesLogicValues {
    currentTeamId: number | null // teamLogic
    config: AccountTrackRulesConfigApi | null
    configLoading: boolean
    draft: AccountTrackRulesConfigApi
    hasUnsavedChanges: boolean
    canSave: boolean
    canPreview: boolean
    previewResponse: AccountTrackRulePreviewApi | null
    previewResponseLoading: boolean
    previewedDraft: AccountTrackRulesConfigApi | null
    previewMatchesDraft: boolean
    runs: AccountTrackRuleRunViewApi[]
    runsLoading: boolean
    currentRun: AccountTrackRuleRunViewApi | null
    currentRunLoading: boolean
    canRun: boolean
    saveResponse: AccountTrackRulesConfigApi | null
    saveResponseLoading: boolean
}

export interface accountTrackRulesLogicActions {
    loadConfig: () => { value: true }
    loadConfigSuccess: (config: AccountTrackRulesConfigApi | null) => { config: AccountTrackRulesConfigApi | null }
    loadConfigFailure: (error: unknown) => { error: unknown }
    saveConfig: () => { value: true }
    saveConfigSuccess: (saveResponse: AccountTrackRulesConfigApi) => { saveResponse: AccountTrackRulesConfigApi }
    saveConfigFailure: (error: unknown) => { error: unknown }
    previewDraft: () => { value: true }
    loadPreview: () => { value: true }
    loadPreviewSuccess: (previewResponse: AccountTrackRulePreviewApi) => {
        previewResponse: AccountTrackRulePreviewApi
    }
    loadPreviewFailure: (error: unknown) => { error: unknown }
    setPreviewedDraft: (config: AccountTrackRulesConfigApi) => { config: AccountTrackRulesConfigApi }
    loadRuns: () => { value: true }
    loadRunsSuccess: (runs: AccountTrackRuleRunViewApi[]) => { runs: AccountTrackRuleRunViewApi[] }
    loadRunsFailure: (error: unknown) => { error: unknown }
    startRun: () => { value: true }
    startRunSuccess: (currentRun: AccountTrackRuleRunViewApi) => { currentRun: AccountTrackRuleRunViewApi }
    startRunFailure: (error: unknown) => { error: unknown }
    setDraft: (config: AccountTrackRulesConfigApi) => { config: AccountTrackRulesConfigApi }
    setEnabled: (enabled: boolean) => { enabled: boolean }
    toggleEnabled: (enabled: boolean) => { enabled: boolean }
    addGroup: () => { value: true }
    updateGroup: (index: number, group: AccountTrackRuleGroupApi) => { index: number; group: AccountTrackRuleGroupApi }
    removeGroup: (index: number) => { index: number }
}

export type accountTrackRulesLogicType = MakeLogicType<accountTrackRulesLogicValues, accountTrackRulesLogicActions>

export const accountTrackRulesLogic = kea<accountTrackRulesLogicType>([
    path(['products', 'customerAnalytics', 'configuration', 'accountTrackRulesLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),

    actions({
        setDraft: (config: AccountTrackRulesConfigApi) => ({ config }),
        setPreviewedDraft: (config: AccountTrackRulesConfigApi) => ({ config }),
        previewDraft: true,
        setEnabled: (enabled: boolean) => ({ enabled }),
        toggleEnabled: (enabled: boolean) => ({ enabled }),
        addGroup: true,
        updateGroup: (index: number, group: AccountTrackRuleGroupApi) => ({ index, group }),
        removeGroup: (index: number) => ({ index }),
    }),

    reducers({
        draft: [
            EMPTY_CONFIG,
            {
                setDraft: (_, { config }) => config,
                setEnabled: (state, { enabled }) => ({ ...state, enabled }),
                addGroup: (state) => ({ ...state, groups: [...state.groups, { conditions: [] }] }),
                updateGroup: (state, { index, group }) => ({
                    ...state,
                    groups: state.groups.map((existing, groupIndex) => (groupIndex === index ? group : existing)),
                }),
                removeGroup: (state, { index }) => ({
                    ...state,
                    groups: state.groups.filter((_, groupIndex) => groupIndex !== index),
                }),
            },
        ],
        previewedDraft: [
            null as AccountTrackRulesConfigApi | null,
            {
                setPreviewedDraft: (_, { config }) => config,
            },
        ],
    }),

    loaders(({ values }) => ({
        config: [
            null as AccountTrackRulesConfigApi | null,
            {
                loadConfig: async () => {
                    if (values.currentTeamId === null) {
                        return null
                    }
                    try {
                        return await accountTrackRulesList(String(values.currentTeamId))
                    } catch (error) {
                        captureUnexpectedApiError(error, 'accountTrackRulesLogic.loadConfig')
                        throw error
                    }
                },
            },
        ],
        saveResponse: [
            null as AccountTrackRulesConfigApi | null,
            {
                saveConfig: async () => {
                    if (values.currentTeamId === null) {
                        throw new Error('No project selected')
                    }
                    try {
                        return await accountTrackRulesUpdate(String(values.currentTeamId), values.draft)
                    } catch (error) {
                        captureUnexpectedApiError(error, 'accountTrackRulesLogic.saveConfig')
                        throw error
                    }
                },
            },
        ],
        previewResponse: [
            null as AccountTrackRulePreviewApi | null,
            {
                loadPreview: async () => {
                    if (values.currentTeamId === null) {
                        throw new Error('No project selected')
                    }
                    try {
                        return await accountTrackRulesPreviewCreate(String(values.currentTeamId), values.draft)
                    } catch (error) {
                        captureUnexpectedApiError(error, 'accountTrackRulesLogic.loadPreview')
                        throw error
                    }
                },
            },
        ],
        runs: [
            [] as AccountTrackRuleRunViewApi[],
            {
                loadRuns: async () => {
                    if (values.currentTeamId === null) {
                        return []
                    }
                    try {
                        return (await accountTrackRulesRunsList(String(values.currentTeamId), { limit: 10 })).results
                    } catch (error) {
                        captureUnexpectedApiError(error, 'accountTrackRulesLogic.loadRuns')
                        throw error
                    }
                },
            },
        ],
        currentRun: [
            null as AccountTrackRuleRunViewApi | null,
            {
                startRun: async () => {
                    if (values.currentTeamId === null) {
                        throw new Error('No project selected')
                    }
                    try {
                        return await accountTrackRulesRunCreate(String(values.currentTeamId), {
                            idempotency_key: uuidv4(),
                            confirmed: true,
                        })
                    } catch (error) {
                        captureUnexpectedApiError(error, 'accountTrackRulesLogic.startRun')
                        throw error
                    }
                },
            },
        ],
    })),

    selectors({
        hasUnsavedChanges: [
            (s) => [s.config, s.draft],
            (config: AccountTrackRulesConfigApi | null, draft: AccountTrackRulesConfigApi): boolean =>
                config !== null && JSON.stringify(config) !== JSON.stringify(draft),
        ],
        canSave: [
            (s) => [s.draft, s.hasUnsavedChanges],
            (draft: AccountTrackRulesConfigApi, hasUnsavedChanges: boolean): boolean =>
                hasUnsavedChanges &&
                (!draft.enabled || draft.groups.length > 0) &&
                draft.groups.every((group) => group.conditions.length > 0),
        ],
        canPreview: [
            (s) => [s.draft],
            (draft: AccountTrackRulesConfigApi): boolean =>
                draft.groups.length > 0 && draft.groups.every((group) => group.conditions.length > 0),
        ],
        previewMatchesDraft: [
            (s) => [s.previewResponse, s.previewedDraft, s.draft],
            (
                previewResponse: AccountTrackRulePreviewApi | null,
                previewedDraft: AccountTrackRulesConfigApi | null,
                draft: AccountTrackRulesConfigApi
            ): boolean => {
                if (!previewResponse || !previewedDraft) {
                    return false
                }
                return JSON.stringify({ ...previewedDraft, version: 0 }) === JSON.stringify({ ...draft, version: 0 })
            },
        ],
        canRun: [
            (s) => [s.config, s.hasUnsavedChanges, s.currentRunLoading, s.currentRun, s.runs],
            (
                config: AccountTrackRulesConfigApi | null,
                hasUnsavedChanges: boolean,
                currentRunLoading: boolean,
                currentRun: AccountTrackRuleRunViewApi | null,
                runs: AccountTrackRuleRunViewApi[]
            ): boolean => {
                const currentRunStillPending =
                    !!currentRun &&
                    !TERMINAL_RUN_STATUSES.has(currentRun.status) &&
                    !runs.some((run) => run.id === currentRun.id && TERMINAL_RUN_STATUSES.has(run.status))
                return (
                    !!config?.enabled &&
                    !hasUnsavedChanges &&
                    !currentRunLoading &&
                    !currentRunStillPending &&
                    !runs.some((run) => !TERMINAL_RUN_STATUSES.has(run.status))
                )
            },
        ],
    }),

    listeners(({ actions, cache, values }) => ({
        loadConfigSuccess: ({ config }) => {
            if (config) {
                actions.setDraft(config)
            }
        },
        loadConfigFailure: () => {
            lemonToast.error('Could not load account track rules')
        },
        saveConfigSuccess: ({ saveResponse }) => {
            const runAfterSave = cache.runAfterSave === true
            cache.runAfterSave = false
            cache.toggleSaveInProgress = false
            actions.setDraft(saveResponse)
            lemonToast.success('Track rules saved')
            actions.loadConfigSuccess(saveResponse)
            if (runAfterSave) {
                actions.startRun()
            }
        },
        saveConfigFailure: ({ error }) => {
            cache.runAfterSave = false
            if (cache.toggleSaveInProgress && values.config) {
                actions.setDraft(values.config)
            }
            cache.toggleSaveInProgress = false
            lemonToast.error(
                error instanceof ApiError && error.status === 409
                    ? 'Track rules changed since this page loaded. Reload and try again.'
                    : 'Could not save track rules. Check every condition and try again.'
            )
        },
        toggleEnabled: ({ enabled }) => {
            cache.runAfterSave = enabled
            cache.toggleSaveInProgress = true
            actions.setEnabled(enabled)
            actions.saveConfig()
        },
        previewDraft: () => {
            cache.pendingPreviewDraft = structuredClone(values.draft)
            actions.loadPreview()
        },
        loadPreviewSuccess: () => {
            if (cache.pendingPreviewDraft) {
                actions.setPreviewedDraft(cache.pendingPreviewDraft)
            }
            cache.pendingPreviewDraft = null
        },
        loadPreviewFailure: ({ error }) => {
            cache.pendingPreviewDraft = null
            lemonToast.error(
                error instanceof ApiError && error.status === 400
                    ? 'Track rules reference an invalid or deleted field.'
                    : 'Could not preview track rules'
            )
        },
        startRunSuccess: () => {
            cache.trackRulesRunPollAttempts = 0
            lemonToast.success('Track rules run started')
            actions.loadRuns()
        },
        startRunFailure: ({ error }) => {
            lemonToast.error(
                error instanceof ApiError && error.status === 409
                    ? 'Another track rules run is already in progress.'
                    : error instanceof ApiError && error.status === 400
                      ? 'Enable and save track rules before running them.'
                      : 'Could not start the track rules run'
            )
        },
        loadRunsSuccess: () => {
            cache.disposables.dispose('trackRulesRunPoll')
            const hasActiveRun = values.runs.some((run) => !TERMINAL_RUN_STATUSES.has(run.status))
            const attempts = (cache.trackRulesRunPollAttempts ?? 0) + 1
            cache.trackRulesRunPollAttempts = attempts
            if (hasActiveRun && attempts < RUN_POLL_MAX_ATTEMPTS) {
                cache.disposables.add(() => {
                    const timeoutId = setTimeout(() => actions.loadRuns(), RUN_POLL_INTERVAL_MS)
                    return () => clearTimeout(timeoutId)
                }, 'trackRulesRunPoll')
            } else if (!hasActiveRun) {
                cache.trackRulesRunPollAttempts = 0
            }
        },
        loadRunsFailure: () => {
            lemonToast.error('Could not load track rules run history')
        },
    })),

    afterMount(({ actions }) => {
        actions.loadConfig()
        actions.loadRuns()
    }),
])
