import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { pluralize } from 'lib/utils/strings'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DataQualitySubjectRef, DataQualitySubjectType, checksApi } from './checksApi'
import { checkDisplayName } from './checksConstants'
import type {
    DataQualityCheckApi,
    DataQualityCheckRunApi,
    DataQualityCheckTypeApi,
    DataQualitySubjectHealthApi,
    DataQualitySuiteRunApi,
} from './generated/api.schemas'
import { CheckTypeEnumApi, DataQualityCheckSeverityEnumApi, SubjectTypeEnumApi } from './generated/api.schemas'

const CHECKS_LIMIT = 100
const SUITE_RUNS_LIMIT = 20
const FAST_POLL_INTERVAL_MS = 3000
const SLOW_POLL_INTERVAL_MS = 15000
const FAST_POLL_WINDOW_MS = 60_000
const POLL_TIMEOUT_MS = 15 * 60_000
const CHECK_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]*$/
const TERMINAL_SUITE_RUN_STATUSES = ['completed', 'failed', 'empty']

export type CheckPendingKind = 'running' | 'deleting' | 'toggling' | 'loadingRuns' | 'loadingSuiteRunRuns'

// Annotated rather than asserted at the use site: the annotation still fails the typecheck if a
// CheckPendingKind is added without seeding its map, and kea-typegen can read the type from here.
// Inlining it with `satisfies` makes typegen infer `{ running: {}, ... }`, which nothing can index.
const EMPTY_PENDING_CHECK_ACTIONS: Record<CheckPendingKind, Record<string, boolean>> = {
    running: {},
    deleting: {},
    toggling: {},
    loadingRuns: {},
    loadingSuiteRunRuns: {},
}

export interface DataQualityChecksLogicProps {
    subjectType: DataQualitySubjectType
    subjectId: string
}

export interface CheckFormValues {
    checkType: CheckTypeEnumApi
    columnName: string
    name: string
    description: string
    severity: DataQualityCheckSeverityEnumApi
    tags: string[]
    acceptedValues: string[]
    toSubjectType: SubjectTypeEnumApi
    toSubjectUuid: string
    toColumn: string
    rowCountMin: number | null
    rowCountMax: number | null
    maxAgeMinutes: number | null
    customSql: string
}

export const EMPTY_CHECK_FORM: CheckFormValues = {
    checkType: CheckTypeEnumApi.NotNull,
    columnName: '',
    name: '',
    description: '',
    severity: DataQualityCheckSeverityEnumApi.Error,
    tags: [],
    acceptedValues: [],
    toSubjectType: SubjectTypeEnumApi.View,
    toSubjectUuid: '',
    toColumn: '',
    rowCountMin: null,
    rowCountMax: null,
    maxAgeMinutes: null,
    customSql: '',
}

export function isTerminalSuiteRun(suiteRun: DataQualitySuiteRunApi | null): boolean {
    return !!suiteRun && TERMINAL_SUITE_RUN_STATUSES.includes(suiteRun.status)
}

function subjectRef(props: DataQualityChecksLogicProps): DataQualitySubjectRef {
    return { subjectType: props.subjectType, subjectId: props.subjectId }
}

function isForbidden(error: unknown): boolean {
    return error instanceof ApiError && error.status === 403
}

function apiErrorDetail(error: unknown): string | null {
    return error instanceof ApiError ? error.detail : null
}

function formToConfig(form: CheckFormValues): Record<string, unknown> {
    switch (form.checkType) {
        case CheckTypeEnumApi.AcceptedValues:
            return { values: form.acceptedValues }
        case CheckTypeEnumApi.Relationships:
            return {
                to_subject_type: form.toSubjectType,
                to_subject_uuid: form.toSubjectUuid,
                to_column: form.toColumn,
            }
        case CheckTypeEnumApi.RowCount: {
            const min = form.rowCountMin ?? null
            const max = form.rowCountMax ?? null
            return { ...(min !== null ? { min } : {}), ...(max !== null ? { max } : {}) }
        }
        case CheckTypeEnumApi.Freshness:
            return { max_age_minutes: form.maxAgeMinutes }
        case CheckTypeEnumApi.CustomSql:
            return { query: form.customSql }
        default:
            return {}
    }
}

function formToCheck(form: CheckFormValues, requiresColumn: boolean): Record<string, unknown> {
    return {
        check_type: form.checkType,
        ...(requiresColumn ? { column_name: form.columnName } : {}),
        config: formToConfig(form),
        severity: form.severity,
        tags: form.tags,
        ...(form.name ? { name: form.name } : {}),
        ...(form.description ? { description: form.description } : {}),
    }
}

function checkToForm(check: DataQualityCheckApi): CheckFormValues {
    const config = check.config ?? {}
    return {
        ...EMPTY_CHECK_FORM,
        checkType: check.check_type,
        columnName: check.column_name ?? '',
        name: check.name ?? '',
        description: check.description ?? '',
        severity: check.severity ?? DataQualityCheckSeverityEnumApi.Error,
        tags: check.tags ?? [],
        acceptedValues: (config.values as string[]) ?? [],
        toSubjectType: (config.to_subject_type as SubjectTypeEnumApi) ?? SubjectTypeEnumApi.View,
        toSubjectUuid: (config.to_subject_uuid as string) ?? '',
        toColumn: (config.to_column as string) ?? '',
        rowCountMin: (config.min as number) ?? null,
        rowCountMax: (config.max as number) ?? null,
        maxAgeMinutes: (config.max_age_minutes as number) ?? null,
        customSql: (config.query as string) ?? '',
    }
}

export function suiteRunSummary(suiteRun: DataQualitySuiteRunApi): string {
    const outcomes: [number, string][] = [
        [suiteRun.checks_passed, 'passed'],
        [suiteRun.checks_failed, 'failed'],
        [suiteRun.checks_errored, 'errored'],
        [suiteRun.checks_skipped, 'skipped'],
    ]
    if (suiteRun.checks_failed === 0 && suiteRun.checks_errored === 0 && suiteRun.checks_passed > 0) {
        return `All ${pluralize(suiteRun.checks_passed, 'check')} passed`
    }
    return outcomes
        .filter(([count]) => count > 0)
        .map(([count, outcome]) => `${count} ${outcome}`)
        .join(', ')
}

function checkSortRank(check: DataQualityCheckApi): number {
    if (check.last_status === 'failed' || check.last_status === 'errored') {
        return 0
    }
    return check.enabled === false ? 2 : 1
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityChecksLogicValues {
    accessDenied: boolean
    activeSuiteRun: DataQualitySuiteRunApi | null
    checkForm: CheckFormValues
    checkFormAllErrors: Record<string, any>
    checkFormChanged: boolean
    checkFormErrors: DeepPartialMap<CheckFormValues, ValidationErrorType>
    checkFormHasErrors: boolean
    checkFormManualErrors: Record<string, any>
    checkFormTouched: boolean
    checkFormTouches: Record<string, boolean>
    checkFormValidationErrors: DeepPartialMap<CheckFormValues, ValidationErrorType>
    checkModalOpen: boolean
    checkRunsByCheckId: Record<string, DataQualityCheckRunApi[]>
    checkTypeByName: {
        [k: string]: DataQualityCheckTypeApi
    }
    checkTypes: DataQualityCheckTypeApi[]
    checkTypesLoading: boolean
    checks: DataQualityCheckApi[]
    checksLoading: boolean
    editingCheck: DataQualityCheckApi | null
    enabledChecksCount: number
    health: DataQualitySubjectHealthApi | null
    healthLoading: boolean
    isCheckFormSubmitting: boolean
    isCheckFormValid: boolean
    isSuiteRunning: boolean
    pendingCheckActions: Record<CheckPendingKind, Record<string, boolean>>
    pollTimedOut: boolean
    runAllInFlight: boolean
    serverError: string | null
    showCheckFormErrors: boolean
    sortedChecks: DataQualityCheckApi[]
    suiteRunCheckRunsBySuiteRunId: Record<string, DataQualityCheckRunApi[]>
    suiteRuns: DataQualitySuiteRunApi[]
    suiteRunsLoading: boolean
    suiteRunsRequested: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityChecksLogicActions {
    loadDatabase: (
        args_0?:
            | {
                  force?: boolean
                  shallow?: boolean
              }
            | undefined
    ) => {
        force?: boolean
        shallow?: boolean
    } // databaseTableListLogic
    adoptRunningSuiteRun: () => {
        value: true
    }
    closeCheckModal: () => {
        value: true
    }
    deleteCheck: (checkId: string) => {
        checkId: string
    }
    finishSuiteRun: (suiteRun: DataQualitySuiteRunApi) => {
        suiteRun: DataQualitySuiteRunApi
    }
    loadCheckRuns: (checkId: string) => {
        checkId: string
    }
    loadCheckTypes: () => any
    loadCheckTypesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCheckTypesSuccess: (
        checkTypes: DataQualityCheckTypeApi[],
        payload?: any
    ) => {
        checkTypes: DataQualityCheckTypeApi[]
        payload?: any
    }
    loadChecks: () => any
    loadChecksFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadChecksSuccess: (
        checks: DataQualityCheckApi[],
        payload?: any
    ) => {
        checks: DataQualityCheckApi[]
        payload?: any
    }
    loadHealth: () => any
    loadHealthFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadHealthSuccess: (
        health: DataQualitySubjectHealthApi,
        payload?: any
    ) => {
        health: DataQualitySubjectHealthApi
        payload?: any
    }
    loadSuiteRunCheckRuns: (suiteRunId: string) => {
        suiteRunId: string
    }
    loadSuiteRuns: () => any
    loadSuiteRunsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSuiteRunsSuccess: (
        suiteRuns: DataQualitySuiteRunApi[],
        payload?: any
    ) => {
        suiteRuns: DataQualitySuiteRunApi[]
        payload?: any
    }
    openCheckModal: (check?: DataQualityCheckApi | null) => {
        check: DataQualityCheckApi | null
    }
    pollActiveSuiteRun: () => {
        value: true
    }
    removeCheck: (checkId: string) => {
        checkId: string
    }
    resetCheckForm: (values?: CheckFormValues) => {
        values?: CheckFormValues
    }
    runAll: () => {
        value: true
    }
    runCheck: (checkId: string) => {
        checkId: string
    }
    scheduleSuiteRunPoll: () => {
        value: true
    }
    setAccessDenied: () => {
        value: true
    }
    setActiveSuiteRun: (suiteRun: DataQualitySuiteRunApi | null) => {
        suiteRun: DataQualitySuiteRunApi | null
    }
    setCheckFormManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setCheckFormValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setCheckFormValues: (values: DeepPartial<CheckFormValues>) => {
        values: DeepPartial<CheckFormValues>
    }
    setCheckPending: (
        kind: CheckPendingKind,
        checkId: string,
        pending: boolean
    ) => {
        checkId: string
        kind: CheckPendingKind
        pending: boolean
    }
    setCheckRuns: (
        checkId: string,
        runs: DataQualityCheckRunApi[]
    ) => {
        checkId: string
        runs: DataQualityCheckRunApi[]
    }
    setPollTimedOut: () => {
        value: true
    }
    setRunAllInFlight: (inFlight: boolean) => {
        inFlight: boolean
    }
    setServerError: (serverError: string | null) => {
        serverError: string | null
    }
    setSuiteRunCheckRuns: (
        suiteRunId: string,
        runs: DataQualityCheckRunApi[]
    ) => {
        runs: DataQualityCheckRunApi[]
        suiteRunId: string
    }
    submitCheckForm: () => {
        value: boolean
    }
    submitCheckFormFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitCheckFormRequest: (checkForm: CheckFormValues) => {
        checkForm: CheckFormValues
    }
    submitCheckFormSuccess: (checkForm: CheckFormValues) => {
        checkForm: CheckFormValues
    }
    toggleCheckEnabled: (
        checkId: string,
        enabled: boolean
    ) => {
        checkId: string
        enabled: boolean
    }
    touchCheckFormField: (key: string) => {
        key: string
    }
    upsertCheck: (check: DataQualityCheckApi) => {
        check: DataQualityCheckApi
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityChecksLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        enabledChecksCount: (checks: DataQualityCheckApi[]) => number
        isSuiteRunning: (activeSuiteRun: DataQualitySuiteRunApi | null, pollTimedOut: boolean) => boolean
        checkTypeByName: (checkTypes: DataQualityCheckTypeApi[]) => {
            [k: string]: DataQualityCheckTypeApi
        }
        sortedChecks: (checks: DataQualityCheckApi[]) => DataQualityCheckApi[]
    }
}

export type dataQualityChecksLogicType = MakeLogicType<
    dataQualityChecksLogicValues,
    dataQualityChecksLogicActions,
    DataQualityChecksLogicProps,
    dataQualityChecksLogicMeta
>

export const dataQualityChecksLogic = kea<dataQualityChecksLogicType>([
    props({} as DataQualityChecksLogicProps),
    key((props: DataQualityChecksLogicProps) => `${props.subjectType}:${props.subjectId}`),
    path((key) => ['products', 'data_quality', 'frontend', 'dataQualityChecksLogic', key]),
    connect(() => ({
        actions: [databaseTableListLogic, ['loadDatabase']],
    })),
    actions({
        openCheckModal: (check: DataQualityCheckApi | null = null) => ({ check }),
        closeCheckModal: true,
        setServerError: (serverError: string | null) => ({ serverError }),
        upsertCheck: (check: DataQualityCheckApi) => ({ check }),
        removeCheck: (checkId: string) => ({ checkId }),
        deleteCheck: (checkId: string) => ({ checkId }),
        toggleCheckEnabled: (checkId: string, enabled: boolean) => ({ checkId, enabled }),
        runCheck: (checkId: string) => ({ checkId }),
        runAll: true,
        setRunAllInFlight: (inFlight: boolean) => ({ inFlight }),
        setCheckPending: (kind: CheckPendingKind, checkId: string, pending: boolean) => ({ kind, checkId, pending }),
        setActiveSuiteRun: (suiteRun: DataQualitySuiteRunApi | null) => ({ suiteRun }),
        scheduleSuiteRunPoll: true,
        pollActiveSuiteRun: true,
        finishSuiteRun: (suiteRun: DataQualitySuiteRunApi) => ({ suiteRun }),
        setPollTimedOut: true,
        adoptRunningSuiteRun: true,
        loadCheckRuns: (checkId: string) => ({ checkId }),
        setCheckRuns: (checkId: string, runs: DataQualityCheckRunApi[]) => ({ checkId, runs }),
        loadSuiteRunCheckRuns: (suiteRunId: string) => ({ suiteRunId }),
        setSuiteRunCheckRuns: (suiteRunId: string, runs: DataQualityCheckRunApi[]) => ({ suiteRunId, runs }),
        setAccessDenied: true,
    }),
    loaders(({ props }) => ({
        checks: [
            [] as DataQualityCheckApi[],
            {
                loadChecks: async () => (await checksApi.list(subjectRef(props), CHECKS_LIMIT)).results,
            },
        ],
        health: [
            null as DataQualitySubjectHealthApi | null,
            {
                loadHealth: async () => await checksApi.health(subjectRef(props)),
            },
        ],
        checkTypes: [
            [] as DataQualityCheckTypeApi[],
            {
                loadCheckTypes: async () => await checksApi.checkTypes(subjectRef(props)),
            },
        ],
        suiteRuns: [
            [] as DataQualitySuiteRunApi[],
            {
                loadSuiteRuns: async () => (await checksApi.suiteRuns(subjectRef(props), SUITE_RUNS_LIMIT)).results,
            },
        ],
    })),
    reducers({
        checkModalOpen: [
            false,
            {
                openCheckModal: () => true,
                closeCheckModal: () => false,
            },
        ],
        editingCheck: [
            null as DataQualityCheckApi | null,
            {
                openCheckModal: (_, { check }) => check,
                closeCheckModal: () => null,
            },
        ],
        serverError: [
            null as string | null,
            {
                setServerError: (_, { serverError }) => serverError,
                openCheckModal: () => null,
                closeCheckModal: () => null,
            },
        ],
        checks: {
            upsertCheck: (state: DataQualityCheckApi[], { check }: { check: DataQualityCheckApi }) =>
                state.some((existing) => existing.id === check.id)
                    ? state.map((existing) => (existing.id === check.id ? check : existing))
                    : [check, ...state],
            removeCheck: (state: DataQualityCheckApi[], { checkId }: { checkId: string }) =>
                state.filter((check) => check.id !== checkId),
        },
        pendingCheckActions: [
            EMPTY_PENDING_CHECK_ACTIONS,
            {
                setCheckPending: (state, { kind, checkId, pending }) => ({
                    ...state,
                    [kind]: { ...state[kind], [checkId]: pending },
                }),
            },
        ],
        runAllInFlight: [
            false,
            {
                runAll: () => true,
                setRunAllInFlight: (_, { inFlight }) => inFlight,
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
        suiteRunCheckRunsBySuiteRunId: [
            {} as Record<string, DataQualityCheckRunApi[]>,
            {
                setSuiteRunCheckRuns: (state, { suiteRunId, runs }) => ({ ...state, [suiteRunId]: runs }),
            },
        ],
        // Tracks whether the run history was ever opened, so completion reloads it even when the
        // first load returned no rows. suiteRuns.length cannot tell "empty" from "never opened".
        suiteRunsRequested: [
            false,
            {
                loadSuiteRuns: () => true,
            },
        ],
        accessDenied: [
            false,
            {
                setAccessDenied: () => true,
            },
        ],
    }),
    selectors({
        enabledChecksCount: [
            (s) => [s.checks],
            (checks: DataQualityCheckApi[]) => checks.filter((check) => check.enabled !== false).length,
        ],
        isSuiteRunning: [
            (s) => [s.activeSuiteRun, s.pollTimedOut],
            (activeSuiteRun: DataQualitySuiteRunApi | null, pollTimedOut: boolean) =>
                !!activeSuiteRun && !isTerminalSuiteRun(activeSuiteRun) && !pollTimedOut,
        ],
        checkTypeByName: [
            (s) => [s.checkTypes],
            (checkTypes: DataQualityCheckTypeApi[]) =>
                Object.fromEntries(checkTypes.map((checkType) => [checkType.check_type, checkType])),
        ],
        sortedChecks: [
            (s) => [s.checks],
            (checks: DataQualityCheckApi[]) =>
                [...checks].sort(
                    (left, right) =>
                        checkSortRank(left) - checkSortRank(right) ||
                        checkDisplayName(left).localeCompare(checkDisplayName(right))
                ),
        ],
    }),
    forms(({ props, values, actions, cache }) => ({
        checkForm: {
            defaults: EMPTY_CHECK_FORM,
            errors: [
                (s: any) => [s.checkForm, s.checkTypeByName],
                (form: CheckFormValues, checkTypeByName: Record<string, DataQualityCheckTypeApi>) => ({
                    name:
                        form.name && !CHECK_NAME_PATTERN.test(form.name)
                            ? 'Use letters, numbers and underscores, starting with a letter.'
                            : undefined,
                    columnName:
                        checkTypeByName[form.checkType]?.requires_column && !form.columnName
                            ? 'Pick a column for this check.'
                            : undefined,
                    acceptedValues:
                        form.checkType === CheckTypeEnumApi.AcceptedValues && form.acceptedValues.length === 0
                            ? 'Add at least one allowed value.'
                            : undefined,
                    toSubjectUuid:
                        form.checkType === CheckTypeEnumApi.Relationships && !form.toSubjectUuid
                            ? 'Pick the table or view this column points at.'
                            : undefined,
                    toColumn:
                        form.checkType === CheckTypeEnumApi.Relationships && !form.toColumn
                            ? 'Pick the column holding the referenced values.'
                            : undefined,
                    rowCountMin:
                        form.checkType === CheckTypeEnumApi.RowCount &&
                        (form.rowCountMin ?? null) === null &&
                        (form.rowCountMax ?? null) === null
                            ? 'Set a minimum, a maximum, or both.'
                            : undefined,
                    rowCountMax:
                        form.checkType === CheckTypeEnumApi.RowCount &&
                        (form.rowCountMin ?? 0) > (form.rowCountMax ?? Infinity)
                            ? 'The maximum has to be at least the minimum.'
                            : undefined,
                    maxAgeMinutes:
                        form.checkType === CheckTypeEnumApi.Freshness && (form.maxAgeMinutes ?? 0) < 1
                            ? 'Set an age of at least one minute.'
                            : undefined,
                    customSql:
                        form.checkType === CheckTypeEnumApi.CustomSql && !form.customSql.trim()
                            ? 'Write the query that selects the failing rows.'
                            : undefined,
                }),
            ],
            submit: async (form: CheckFormValues) => {
                // A form can be submitted with Enter while the request is already in flight, which
                // the button's loading state cannot prevent.
                if (cache.savingCheck) {
                    return
                }
                cache.savingCheck = true
                actions.setServerError(null)
                const editing = values.editingCheck
                try {
                    const saved = editing
                        ? await checksApi.partialUpdate(subjectRef(props), editing.id, {
                              name: form.name,
                              description: form.description,
                              severity: form.severity,
                              tags: form.tags,
                          })
                        : await checksApi.create(
                              subjectRef(props),
                              formToCheck(form, !!values.checkTypeByName[form.checkType]?.requires_column) as any
                          )
                    actions.upsertCheck(saved)
                    actions.closeCheckModal()
                    actions.loadHealth()
                    lemonToast.success('Check saved', {
                        button: { label: 'Run now', action: () => actions.runCheck(saved.id) },
                    })
                } catch (error) {
                    actions.setServerError(apiErrorDetail(error) ?? 'Could not save the check. Try again.')
                    throw error
                } finally {
                    cache.savingCheck = false
                }
            },
        },
    })),
    listeners(({ props, values, actions, cache }) => ({
        loadChecksFailure: ({ errorObject }) => {
            if (isForbidden(errorObject)) {
                actions.setAccessDenied()
            }
        },
        loadHealthFailure: ({ errorObject }) => {
            if (isForbidden(errorObject)) {
                actions.setAccessDenied()
            }
        },
        openCheckModal: ({ check }) => {
            actions.resetCheckForm(check ? checkToForm(check) : EMPTY_CHECK_FORM)
            if (!values.checkTypes.length) {
                actions.loadCheckTypes()
            }
            // The relationships picker offers the project's warehouse subjects.
            actions.loadDatabase()
        },
        deleteCheck: async ({ checkId }) => {
            if (values.pendingCheckActions.deleting[checkId]) {
                return
            }
            actions.setCheckPending('deleting', checkId, true)
            try {
                await checksApi.destroy(subjectRef(props), checkId)
                actions.removeCheck(checkId)
                actions.loadHealth()
            } catch (error) {
                lemonToast.error(apiErrorDetail(error) ?? 'Could not delete the check. Try again.')
            } finally {
                actions.setCheckPending('deleting', checkId, false)
            }
        },
        toggleCheckEnabled: async ({ checkId, enabled }) => {
            if (values.pendingCheckActions.toggling[checkId]) {
                return
            }
            actions.setCheckPending('toggling', checkId, true)
            try {
                actions.upsertCheck(await checksApi.partialUpdate(subjectRef(props), checkId, { enabled }))
                actions.loadHealth()
            } catch (error) {
                lemonToast.error(apiErrorDetail(error) ?? 'Could not update the check. Try again.')
            } finally {
                actions.setCheckPending('toggling', checkId, false)
            }
        },
        loadCheckRuns: async ({ checkId }) => {
            if (values.pendingCheckActions.loadingRuns[checkId]) {
                return
            }
            actions.setCheckPending('loadingRuns', checkId, true)
            try {
                actions.setCheckRuns(checkId, await checksApi.runs(subjectRef(props), checkId))
            } catch (error) {
                lemonToast.error(apiErrorDetail(error) ?? 'Could not load the run history. Try again.')
            } finally {
                actions.setCheckPending('loadingRuns', checkId, false)
            }
        },
        loadSuiteRunCheckRuns: async ({ suiteRunId }) => {
            if (values.pendingCheckActions.loadingSuiteRunRuns[suiteRunId]) {
                return
            }
            actions.setCheckPending('loadingSuiteRunRuns', suiteRunId, true)
            try {
                actions.setSuiteRunCheckRuns(
                    suiteRunId,
                    await checksApi.suiteRunCheckRuns(subjectRef(props), suiteRunId)
                )
            } catch (error) {
                lemonToast.error(apiErrorDetail(error) ?? 'Could not load the run details. Try again.')
            } finally {
                actions.setCheckPending('loadingSuiteRunRuns', suiteRunId, false)
            }
        },
        runCheck: async ({ checkId }) => {
            if (values.pendingCheckActions.running[checkId]) {
                return
            }
            actions.setCheckPending('running', checkId, true)
            // The pending guard is per check, and "Run all" is not blocked by it either, so two
            // starts can be in flight at once. Only the newest one's run may become active:
            // otherwise a slower earlier request lands last and the panel polls the older run.
            cache.suiteStartToken = (cache.suiteStartToken ?? 0) + 1
            const startToken = cache.suiteStartToken
            try {
                const started = await checksApi.run(subjectRef(props), checkId)
                if (cache.suiteStartToken === startToken) {
                    actions.setActiveSuiteRun(started)
                }
            } catch (error) {
                lemonToast.error(apiErrorDetail(error) ?? 'Could not start the check. Try again.')
            } finally {
                actions.setCheckPending('running', checkId, false)
            }
        },
        runAll: async () => {
            cache.suiteStartToken = (cache.suiteStartToken ?? 0) + 1
            const startToken = cache.suiteStartToken
            try {
                const started = await checksApi.runAll(subjectRef(props))
                if (cache.suiteStartToken === startToken) {
                    actions.setActiveSuiteRun(started)
                }
            } catch (error) {
                lemonToast.error(apiErrorDetail(error) ?? 'Could not start the checks. Try again.')
            } finally {
                actions.setRunAllInFlight(false)
            }
        },
        setActiveSuiteRun: ({ suiteRun }) => {
            cache.disposables.dispose('suiteRunPoll')
            cache.pollElapsedMs = 0
            if (!suiteRun) {
                return
            }
            if (isTerminalSuiteRun(suiteRun)) {
                actions.finishSuiteRun(suiteRun)
                return
            }
            actions.scheduleSuiteRunPoll()
        },
        scheduleSuiteRunPoll: () => {
            const delay = cache.pollElapsedMs < FAST_POLL_WINDOW_MS ? FAST_POLL_INTERVAL_MS : SLOW_POLL_INTERVAL_MS
            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => {
                    cache.pollElapsedMs += delay
                    actions.pollActiveSuiteRun()
                }, delay)
                return () => clearTimeout(timeoutId)
            }, 'suiteRunPoll')
        },
        pollActiveSuiteRun: async () => {
            const running = values.activeSuiteRun
            if (!running) {
                return
            }
            let polled: DataQualitySuiteRunApi
            try {
                polled = await checksApi.suiteRunRetrieve(subjectRef(props), running.id)
            } catch (error) {
                // A permanent 403 — the flag turned off mid-run, or query access revoked — takes the
                // panel's access-denied path immediately, like every other request here.
                if (isForbidden(error)) {
                    actions.setAccessDenied()
                    return
                }
                // Other failures are treated as transient and not worth a toast; the next poll retries
                // until the timeout, so a persistently failing request stops rather than polling forever.
                if (cache.pollElapsedMs >= POLL_TIMEOUT_MS) {
                    actions.setPollTimedOut()
                    return
                }
                actions.scheduleSuiteRunPoll()
                return
            }
            // A newer run may have started while this retrieve was in flight. A stale terminal
            // response would otherwise finish the old run and dispose the newer run's poll.
            if (cache.disposables.isDisposed || values.activeSuiteRun?.id !== running.id) {
                return
            }
            if (isTerminalSuiteRun(polled)) {
                actions.finishSuiteRun(polled)
                return
            }
            if (cache.pollElapsedMs >= POLL_TIMEOUT_MS) {
                actions.setPollTimedOut()
                return
            }
            actions.scheduleSuiteRunPoll()
        },
        finishSuiteRun: ({ suiteRun }) => {
            cache.disposables.dispose('suiteRunPoll')
            actions.loadChecks()
            actions.loadHealth()
            Object.keys(values.checkRunsByCheckId).forEach((checkId) => actions.loadCheckRuns(checkId))
            // An adopted or MCP-triggered suite can be expanded while it is still running, so its
            // rows are cached mid-flight. Without this they stay stale until it is reopened.
            Object.keys(values.suiteRunCheckRunsBySuiteRunId).forEach((suiteRunId) =>
                actions.loadSuiteRunCheckRuns(suiteRunId)
            )
            if (values.suiteRunsRequested) {
                actions.loadSuiteRuns()
            }
            if (suiteRun.status === 'empty') {
                lemonToast.info('No enabled checks to run')
            } else if (suiteRun.status === 'failed' && !suiteRun.checks_failed) {
                lemonToast.error(suiteRun.error || 'The checks could not be run. Try again.')
            } else if (suiteRun.checks_failed || suiteRun.checks_errored) {
                lemonToast.warning(suiteRunSummary(suiteRun))
            } else {
                lemonToast.success(suiteRunSummary(suiteRun))
            }
        },
        adoptRunningSuiteRun: async () => {
            try {
                const [newest] = (await checksApi.suiteRuns(subjectRef(props), 1)).results
                if (newest && !isTerminalSuiteRun(newest) && !values.activeSuiteRun) {
                    actions.setActiveSuiteRun(newest)
                }
            } catch (error) {
                if (isForbidden(error)) {
                    actions.setAccessDenied()
                }
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadChecks()
        actions.loadHealth()
        actions.adoptRunningSuiteRun()
    }),
])
