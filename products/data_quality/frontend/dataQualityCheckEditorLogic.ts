import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils/objects'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { performQuery } from '~/queries/query'
import {
    AccessControlFilterWarning,
    type DatabaseSchemaDataWarehouseTable,
    type DatabaseSchemaField,
    type DatabaseSchemaViewTable,
    DataWarehouseSyncWarning,
    HogQLQuery,
    NodeKind,
} from '~/queries/schema/schema-general'

import { DataQualitySubjectRef, checksApi } from './checksApi'
import type {
    DataQualityCheckApi,
    DataQualityCheckTypeApi,
    DataQualityMetricSubjectApi,
    DataQualityOutputColumnApi,
    DataQualityOutputSchemaApi,
} from './generated/api.schemas'
import { CheckTypeEnumApi, DataQualityCheckSeverityEnumApi, SubjectTypeEnumApi } from './generated/api.schemas'

const CHECK_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]*$/

export const METRIC_CHECK_QUERY_TEMPLATE = 'SELECT *\nFROM {metric}\nWHERE <failure condition>'

/** Stable code the API returns when another active check already asserts the same thing. */
const DUPLICATE_DEFINITION_CODE = 'duplicate_definition'

const DENIED_REFERENCE_MESSAGE = "You don't have access to all data referenced by this check."

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

/** A warehouse table or view a relationships check can point at. */
export interface RelationshipSubject {
    id: string
    name: string
    type: SubjectTypeEnumApi
    fields: string[]
    outputSchema: DataQualityOutputColumnApi[]
}

export interface SelectableSubject {
    id: string
    name: string
    type: SubjectTypeEnumApi
}

export interface CustomSqlPreview {
    sql: string
    columns: string[]
    rows: unknown[][]
    rowCount: number
    hasMore: boolean
    /** Sources this query read that are stale, or resources access control filtered out, so the verdict is not final. */
    warnings: (DataWarehouseSyncWarning | AccessControlFilterWarning)[]
}

export interface DataQualityCheckEditorLogicProps {
    /** Which surface mounted this editor. One editor per surface, never one per row. */
    surface: string
    onSaved?: (check: DataQualityCheckApi) => void
    onRunNow?: (check: DataQualityCheckApi) => void
    onClosed?: () => void
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

/** Only the selected type's configuration, so switching type cannot leave stale values behind. */
function definitionPayload(form: CheckFormValues, requiresColumn: boolean): CheckDefinitionPayload {
    return {
        check_type: form.checkType,
        column_name: requiresColumn ? form.columnName : '',
        config: formToConfig(form),
    }
}

type CheckDefinitionPayload = Pick<CheckCreatePayload, 'check_type' | 'column_name' | 'config'>
type CheckCreatePayload = Parameters<typeof checksApi.create>[1]
type CheckEditPayload = Parameters<typeof checksApi.partialUpdate>[2]

export function checkCreatePayload(form: CheckFormValues, requiresColumn: boolean): CheckCreatePayload {
    return {
        ...definitionPayload(form, requiresColumn),
        severity: form.severity,
        tags: form.tags,
        ...(form.name ? { name: form.name } : {}),
        ...(form.description ? { description: form.description } : {}),
    }
}

/** Whether the form asserts something other than what the stored check already asserts. */
function assertionChanged(definition: CheckDefinitionPayload, check: DataQualityCheckApi): boolean {
    return (
        definition.check_type !== check.check_type ||
        definition.column_name !== (check.column_name ?? '') ||
        !objectsEqual(definition.config, check.config ?? {})
    )
}

export function checkEditPayload(
    form: CheckFormValues,
    requiresColumn: boolean,
    editingCheck: DataQualityCheckApi
): CheckEditPayload {
    const definition = definitionPayload(form, requiresColumn)
    return {
        // The backend revalidates the definition whenever the request carries one, and a subject that
        // stopped supporting its check fails that. Send it only when the assertion actually changed,
        // so renaming a check or lowering its severity stays possible.
        ...(assertionChanged(definition, editingCheck) ? definition : {}),
        severity: form.severity,
        // Sent even when blank, unlike create: an edit is how metadata gets cleared.
        name: form.name,
        description: form.description,
        tags: form.tags,
    }
}

export function checkToForm(check: DataQualityCheckApi): CheckFormValues {
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

/** Which form field a config-level server error belongs beside, per check type. */
function configFieldFor(checkType: CheckTypeEnumApi): keyof CheckFormValues | null {
    switch (checkType) {
        case CheckTypeEnumApi.AcceptedValues:
            return 'acceptedValues'
        case CheckTypeEnumApi.Relationships:
            return 'toSubjectUuid'
        case CheckTypeEnumApi.RowCount:
            return 'rowCountMin'
        case CheckTypeEnumApi.Freshness:
            return 'maxAgeMinutes'
        case CheckTypeEnumApi.CustomSql:
            return 'customSql'
        default:
            return null
    }
}

const FIELD_BY_ATTR: Record<string, keyof CheckFormValues> = {
    name: 'name',
    description: 'description',
    severity: 'severity',
    tags: 'tags',
    check_type: 'checkType',
    column_name: 'columnName',
}

/** The form errors a rejected save maps to. Empty means the failure belongs in the modal banner. */
export function serverFieldErrors(
    error: unknown,
    checkType: CheckTypeEnumApi
): Partial<Record<keyof CheckFormValues, string>> {
    if (!(error instanceof ApiError) || !error.detail) {
        return {}
    }
    // The whole assertion is at fault, not one field of it, so every part of it is highlighted.
    if (error.code === DUPLICATE_DEFINITION_CODE) {
        const configField = configFieldFor(checkType)
        return {
            checkType: error.detail,
            columnName: error.detail,
            ...(configField ? { [configField]: error.detail } : {}),
        }
    }
    if (error.attr === 'config') {
        const configField = configFieldFor(checkType)
        return configField ? { [configField]: error.detail } : {}
    }
    const field = error.attr ? FIELD_BY_ATTR[error.attr] : undefined
    return field ? { [field]: error.detail } : {}
}

function generalErrorMessage(error: unknown): string {
    if (error instanceof ApiError && error.status === 403) {
        return DENIED_REFERENCE_MESSAGE
    }
    return (error instanceof ApiError ? error.detail : null) ?? 'Could not save the check. Try again.'
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityCheckEditorLogicValues {
    dataWarehouseTables: DatabaseSchemaDataWarehouseTable[] // databaseTableListLogic
    databaseLoadError: string | null // databaseTableListLogic
    databaseLoading: boolean // databaseTableListLogic
    views: DatabaseSchemaViewTable[] // databaseTableListLogic
    availableColumns: string[]
    availableOutputSchema: DataQualityOutputColumnApi[]
    checkForm: CheckFormValues
    checkFormAllErrors: Record<string, any>
    checkFormChanged: boolean
    checkFormErrors: DeepPartialMap<CheckFormValues, ValidationErrorType>
    checkFormHasErrors: boolean
    checkFormManualErrors: Record<string, any>
    checkFormTouched: boolean
    checkFormTouches: Record<string, boolean>
    checkFormValidationErrors: DeepPartialMap<CheckFormValues, ValidationErrorType>
    checkTypeByName: {
        [k: string]: DataQualityCheckTypeApi
    }
    checkTypes: DataQualityCheckTypeApi[]
    checkTypesError: boolean
    checkTypesLoading: boolean
    customSqlEditorError: string | null
    customSqlPreview: CustomSqlPreview | null
    customSqlPreviewError: string | null
    customSqlPreviewLoading: boolean
    customSqlPreviewStale: boolean
    customSqlPreviewVerdict: 'fail' | 'pass' | null
    customSqlQueryKey: string
    customSqlSourceQuery: HogQLQuery
    customSqlValidationLoading: boolean
    editingCheck: DataQualityCheckApi | null
    isCheckFormSubmitting: boolean
    isCheckFormValid: boolean
    isMetricSubject: boolean
    isOpen: boolean
    metricOutputSchema: DataQualityOutputSchemaApi | null
    metricOutputSchemaError: string | null
    metricOutputSchemaLoading: boolean
    metricSubjects: DataQualityMetricSubjectApi[]
    metricSubjectsError: string | null
    metricSubjectsLoading: boolean
    needsWarehouseCatalog: boolean
    openedWithoutSubject: boolean
    relationshipSubjects: RelationshipSubject[]
    requiresColumn: boolean
    selectableSubjects: SelectableSubject[]
    serverError: string | null
    showCheckFormErrors: boolean
    subject: DataQualitySubjectRef | null
    subjectColumns: string[]
    subjectOutputSchema: DataQualityOutputColumnApi[]
    warehouseCatalogRequested: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityCheckEditorLogicActions {
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
    closeEditor: () => {
        value: true
    }
    loadCheckTypes: () => {
        value: true
    }
    loadCheckTypesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCheckTypesSuccess: (
        checkTypes: DataQualityCheckTypeApi[],
        payload?: {
            value: true
        }
    ) => {
        checkTypes: DataQualityCheckTypeApi[]
        payload?: {
            value: true
        }
    }
    loadMetricOutputSchema: (_: any) => any
    loadMetricOutputSchemaFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMetricOutputSchemaSuccess: (
        metricOutputSchema: DataQualityOutputSchemaApi | null,
        payload?: any
    ) => {
        metricOutputSchema: DataQualityOutputSchemaApi | null
        payload?: any
    }
    loadMetricSubjects: () => any
    loadMetricSubjectsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMetricSubjectsSuccess: (
        metricSubjects: DataQualityMetricSubjectApi[],
        payload?: any
    ) => {
        metricSubjects: DataQualityMetricSubjectApi[]
        payload?: any
    }
    loadWarehouseCatalog: () => {
        value: true
    }
    openEditor: (
        check: DataQualityCheckApi | null,
        subject: DataQualitySubjectRef | null,
        columns?: string[],
        outputSchema?: DataQualityOutputColumnApi[]
    ) => {
        check: DataQualityCheckApi | null
        columns: string[]
        outputSchema: DataQualityOutputColumnApi[]
        subject: DataQualitySubjectRef | null
    }
    requestClose: () => {
        value: true
    }
    resetCheckForm: (values?: CheckFormValues) => {
        values?: CheckFormValues
    }
    runCustomSqlPreview: (_: any) => any
    runCustomSqlPreviewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    runCustomSqlPreviewSuccess: (
        customSqlPreview: CustomSqlPreview | null,
        payload?: any
    ) => {
        customSqlPreview: CustomSqlPreview | null
        payload?: any
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
    setCustomSqlEditorError: (error: string | null) => {
        error: string | null
    }
    setCustomSqlValidationLoading: (loading: boolean) => {
        loading: boolean
    }
    setServerError: (serverError: string | null) => {
        serverError: string | null
    }
    setSubject: (subject: DataQualitySubjectRef) => {
        subject: DataQualitySubjectRef
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
    touchCheckFormField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dataQualityCheckEditorLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        isMetricSubject: (subject: DataQualitySubjectRef | null) => boolean
        checkTypeByName: (checkTypes: DataQualityCheckTypeApi[]) => {
            [k: string]: DataQualityCheckTypeApi
        }
        relationshipSubjects: (
            views: DatabaseSchemaViewTable[],
            dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
        ) => RelationshipSubject[]
        selectableSubjects: (
            relationshipSubjects: RelationshipSubject[],
            metricSubjects: DataQualityMetricSubjectApi[]
        ) => SelectableSubject[]
        availableOutputSchema: (
            subjectColumns: string[],
            subjectOutputSchema: DataQualityOutputColumnApi[],
            subject: DataQualitySubjectRef | null,
            relationshipSubjects: RelationshipSubject[],
            metricOutputSchema: DataQualityOutputSchemaApi | null
        ) => DataQualityOutputColumnApi[]
        availableColumns: (availableOutputSchema: DataQualityOutputColumnApi[]) => string[]
        customSqlSourceQuery: (checkForm: CheckFormValues) => HogQLQuery
        customSqlPreviewStale: (customSqlPreview: CustomSqlPreview | null, checkForm: CheckFormValues) => boolean
        customSqlPreviewVerdict: (customSqlPreview: CustomSqlPreview | null) => 'fail' | 'pass' | null
        requiresColumn: (
            checkForm: CheckFormValues,
            checkTypeByName: {
                [k: string]: DataQualityCheckTypeApi
            }
        ) => boolean
        needsWarehouseCatalog: (
            checkForm: CheckFormValues,
            requiresColumn: boolean,
            subjectColumns: string[],
            subject: DataQualitySubjectRef | null
        ) => boolean
    }
}

export type dataQualityCheckEditorLogicType = MakeLogicType<
    dataQualityCheckEditorLogicValues,
    dataQualityCheckEditorLogicActions,
    DataQualityCheckEditorLogicProps,
    dataQualityCheckEditorLogicMeta
>

/**
 * The one check editor, shared by the subject pages and the project overview.
 *
 * It never reaches back into whichever surface opened it: the mounting surface passes
 * `onSaved` / `onRunNow` / `onClosed`, so refreshing rows, running a check, and restoring focus
 * stay with the surface that knows how to do them.
 */
export const dataQualityCheckEditorLogic = kea<dataQualityCheckEditorLogicType>([
    props({} as DataQualityCheckEditorLogicProps),
    key((props: DataQualityCheckEditorLogicProps) => props.surface),
    path((key) => ['products', 'data_quality', 'frontend', 'dataQualityCheckEditorLogic', key]),
    connect(() => ({
        actions: [databaseTableListLogic, ['loadDatabase']],
        values: [databaseTableListLogic, ['views', 'dataWarehouseTables', 'databaseLoading', 'databaseLoadError']],
    })),
    actions({
        loadCheckTypes: true,
        openEditor: (
            check: DataQualityCheckApi | null,
            subject: DataQualitySubjectRef | null,
            columns: string[] = [],
            outputSchema: DataQualityOutputColumnApi[] = []
        ) => ({
            check,
            subject,
            columns,
            outputSchema,
        }),
        setSubject: (subject: DataQualitySubjectRef) => ({ subject }),
        requestClose: true,
        closeEditor: true,
        setServerError: (serverError: string | null) => ({ serverError }),
        setCustomSqlEditorError: (error: string | null) => ({ error }),
        setCustomSqlValidationLoading: (loading: boolean) => ({ loading }),
        loadWarehouseCatalog: true,
    }),
    loaders(({ values }) => ({
        metricSubjects: [
            [] as DataQualityMetricSubjectApi[],
            {
                loadMetricSubjects: async () => checksApi.metricSubjects(),
            },
        ],
        metricOutputSchema: [
            null as DataQualityOutputSchemaApi | null,
            {
                loadMetricOutputSchema: async (_, breakpoint): Promise<DataQualityOutputSchemaApi | null> => {
                    const subject = values.subject
                    if (subject?.subjectType !== SubjectTypeEnumApi.Metric) {
                        return null
                    }
                    const schema = await checksApi.outputSchema(subject)
                    breakpoint()
                    return values.subject === subject ? schema : null
                },
            },
        ],
        checkTypes: [
            [] as DataQualityCheckTypeApi[],
            {
                loadCheckTypes: async (_, breakpoint) => {
                    let checkTypes: DataQualityCheckTypeApi[]
                    try {
                        checkTypes = values.subject ? await checksApi.checkTypes(values.subject) : []
                    } catch (error) {
                        // A subject change starts a second request. Drop a superseded one so its late
                        // failure cannot report the catalog as unavailable while the newer one runs.
                        breakpoint()
                        throw error
                    }
                    breakpoint()
                    return checkTypes
                },
            },
        ],
        customSqlPreview: [
            null as CustomSqlPreview | null,
            {
                runCustomSqlPreview: async (_, breakpoint): Promise<CustomSqlPreview | null> => {
                    const subject = values.subject
                    const sql = values.checkForm.customSql.trim()
                    // Force a fresh calculation: the scheduled check run always reads current data, so the
                    // preview must not serve a cached result that could report a different verdict.
                    let response: NonNullable<HogQLQuery['response']>
                    try {
                        response = await performQuery<HogQLQuery>(
                            { kind: NodeKind.HogQLQuery, query: sql },
                            undefined,
                            'force_blocking'
                        )
                    } catch (error) {
                        // Cmd+Enter can start a second preview while one is in flight. Drop a superseded
                        // request so its late failure cannot replace the newer result with a stale error.
                        breakpoint()
                        if (values.subject !== subject) {
                            return null
                        }
                        throw error
                    }
                    // Same guard on the success path: a superseded result must not overwrite the newer one.
                    breakpoint()
                    if (values.subject !== subject) {
                        return null
                    }
                    return {
                        sql,
                        columns: response.columns ?? [],
                        rows: response.results.slice(0, 10) as unknown[][],
                        rowCount: response.results.length,
                        hasMore: !!response.hasMore,
                        warnings: response.warnings ?? [],
                    }
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        customSqlQueryKey: [`data-quality-check/${props.surface}`, {}],
        isOpen: [
            false,
            {
                openEditor: () => true,
                closeEditor: () => false,
            },
        ],
        editingCheck: [
            null as DataQualityCheckApi | null,
            {
                openEditor: (_, { check }) => check,
                closeEditor: () => null,
            },
        ],
        subject: [
            null as DataQualitySubjectRef | null,
            {
                openEditor: (_, { subject }) => subject,
                setSubject: (_, { subject }) => subject,
            },
        ],
        openedWithoutSubject: [
            false,
            {
                openEditor: (_, { subject }) => subject === null,
            },
        ],
        subjectColumns: [
            [] as string[],
            {
                openEditor: (_, { columns }) => columns,
            },
        ],
        subjectOutputSchema: [
            [] as DataQualityOutputColumnApi[],
            {
                openEditor: (_, { outputSchema }) => outputSchema,
            },
        ],
        // Keep the full catalog available across modal opens, while avoiding refetches on type switches.
        warehouseCatalogRequested: [
            false,
            {
                loadWarehouseCatalog: () => true,
            },
        ],
        checkTypes: [
            [] as DataQualityCheckTypeApi[],
            {
                openEditor: () => [],
                setSubject: () => [],
            },
        ],
        metricOutputSchema: [
            null as DataQualityOutputSchemaApi | null,
            {
                openEditor: () => null,
                setSubject: () => null,
            },
        ],
        metricSubjectsError: [
            null as string | null,
            {
                loadMetricSubjects: () => null,
                loadMetricSubjectsSuccess: () => null,
                loadMetricSubjectsFailure: (_, { error, errorObject }) => errorObject?.detail ?? error,
                openEditor: () => null,
            },
        ],
        metricOutputSchemaError: [
            null as string | null,
            {
                loadMetricOutputSchema: () => null,
                loadMetricOutputSchemaSuccess: () => null,
                loadMetricOutputSchemaFailure: (_, { error, errorObject }) => errorObject?.detail ?? error,
                openEditor: () => null,
                setSubject: () => null,
            },
        ],
        serverError: [
            null as string | null,
            {
                setServerError: (_, { serverError }) => serverError,
                openEditor: () => null,
                closeEditor: () => null,
            },
        ],
        checkTypesError: [
            false,
            {
                loadCheckTypes: () => false,
                loadCheckTypesSuccess: () => false,
                loadCheckTypesFailure: () => true,
                openEditor: () => false,
                setSubject: () => false,
            },
        ],
        customSqlPreview: [
            null as CustomSqlPreview | null,
            {
                runCustomSqlPreviewSuccess: (_, { customSqlPreview }) => customSqlPreview,
                openEditor: () => null,
            },
        ],
        customSqlPreviewError: [
            null as string | null,
            {
                runCustomSqlPreview: () => null,
                runCustomSqlPreviewSuccess: () => null,
                runCustomSqlPreviewFailure: (_, { error, errorObject }) => errorObject?.detail ?? error,
                openEditor: () => null,
                setCheckFormValue: (state, { name }) => (name === 'customSql' ? null : state),
                setCheckFormValues: (state, { values }) => ('customSql' in values ? null : state),
            },
        ],
        customSqlEditorError: [
            null as string | null,
            {
                setCustomSqlEditorError: (_, { error }) => error,
                openEditor: () => null,
            },
        ],
        customSqlValidationLoading: [
            false,
            {
                // An edit is what starts the wait, so the editor can only end it. The editor also
                // validates the query it was opened with, and that pass must not block saving a
                // check whose query nobody touched.
                setCustomSqlValidationLoading: (state, { loading }) => state && loading,
                openEditor: () => false,
                setCheckFormValue: (state, { name }) =>
                    name === 'customSql' ? true : name === 'checkType' ? false : state,
                setCheckFormValues: (state, { values }) =>
                    'checkType' in values && values.checkType !== CheckTypeEnumApi.CustomSql ? false : state,
            },
        ],
    })),
    selectors({
        isMetricSubject: [
            (s) => [s.subject],
            (subject: DataQualitySubjectRef | null): boolean => subject?.subjectType === 'metric',
        ],
        checkTypeByName: [
            (s) => [s.checkTypes],
            (checkTypes: DataQualityCheckTypeApi[]) =>
                Object.fromEntries(checkTypes.map((checkType) => [checkType.check_type, checkType])),
        ],
        relationshipSubjects: [
            (s) => [s.views, s.dataWarehouseTables],
            (
                views: DatabaseSchemaViewTable[],
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
            ): RelationshipSubject[] =>
                // Only warehouse subjects carry the uuid a relationships check references;
                // PostHog-native and system tables have no check subject to point at.
                [
                    ...views.map((view) => ({ ...view, type: SubjectTypeEnumApi.View })),
                    ...dataWarehouseTables.map((table) => ({ ...table, type: SubjectTypeEnumApi.Table })),
                ]
                    .filter((subject) => !!subject.id)
                    .map((subject) => ({
                        id: subject.id,
                        name: subject.name,
                        type: subject.type,
                        fields: Object.keys(subject.fields ?? {}),
                        outputSchema: Object.entries(subject.fields ?? {}).map(
                            ([name, field]: [string, DatabaseSchemaField]) => ({
                                name,
                                type: field.type ?? null,
                            })
                        ),
                    })),
        ],
        selectableSubjects: [
            (s) => [s.relationshipSubjects, s.metricSubjects],
            (
                relationshipSubjects: RelationshipSubject[],
                metricSubjects: DataQualityMetricSubjectApi[]
            ): SelectableSubject[] => [
                ...relationshipSubjects.map(({ id, name, type }) => ({ id, name, type })),
                ...metricSubjects.map((metric) => ({
                    id: metric.id,
                    name: metric.display_name || metric.name,
                    type: SubjectTypeEnumApi.Metric,
                })),
            ],
        ],
        availableOutputSchema: [
            (s) => [s.subjectColumns, s.subjectOutputSchema, s.subject, s.relationshipSubjects, s.metricOutputSchema],
            (
                subjectColumns: string[],
                subjectOutputSchema: DataQualityOutputColumnApi[],
                subject: DataQualitySubjectRef | null,
                relationshipSubjects: RelationshipSubject[],
                metricOutputSchema: DataQualityOutputSchemaApi | null
            ): DataQualityOutputColumnApi[] => {
                if (subject?.subjectType === SubjectTypeEnumApi.Metric) {
                    return metricOutputSchema?.columns ?? []
                }
                if (subjectOutputSchema.length) {
                    return subjectOutputSchema
                }
                const catalogSubject = relationshipSubjects.find(
                    (candidate) => candidate.id === subject?.subjectId && candidate.type === subject?.subjectType
                )
                return catalogSubject?.outputSchema ?? subjectColumns.map((name) => ({ name, type: null }))
            },
        ],
        availableColumns: [
            (s) => [s.availableOutputSchema],
            (availableOutputSchema: DataQualityOutputColumnApi[]) => availableOutputSchema.map(({ name }) => name),
        ],
    }),
    forms(({ props, values, actions, cache }) => ({
        checkForm: {
            defaults: EMPTY_CHECK_FORM,
            errors: [
                (s: any) => [
                    s.checkForm,
                    s.checkTypeByName,
                    s.customSqlEditorError,
                    s.customSqlValidationLoading,
                    s.isMetricSubject,
                ],
                (
                    form: CheckFormValues,
                    checkTypeByName: Record<string, DataQualityCheckTypeApi>,
                    customSqlEditorError: string | null,
                    customSqlValidationLoading: boolean,
                    isMetricSubject: boolean
                ) => ({
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
                        form.checkType === CheckTypeEnumApi.CustomSql
                            ? !form.customSql.trim()
                                ? 'Write the query that selects the failing rows.'
                                : !isMetricSubject && customSqlValidationLoading
                                  ? 'Checking query...'
                                  : !isMetricSubject
                                    ? (customSqlEditorError ?? undefined)
                                    : undefined
                            : undefined,
                }),
            ],
            submit: async (form: CheckFormValues) => {
                // A form can be submitted with Enter while the request is already in flight, or
                // while the check-type catalog is still arriving, neither of which the button's own
                // disabled state can prevent. Without the catalog there is no column requirement to
                // validate against, so the payload would omit column_name and be rejected.
                // Only while it is in flight: a catalog that failed to load must not wedge the form.
                const catalogPending = values.checkTypesLoading && !values.checkTypes.length
                if (cache.savingCheck || !values.subject || catalogPending) {
                    return
                }
                cache.savingCheck = true
                actions.setServerError(null)
                const editing = values.editingCheck
                try {
                    const saved = editing
                        ? await checksApi.partialUpdate(
                              values.subject,
                              editing.id,
                              checkEditPayload(form, values.requiresColumn, editing)
                          )
                        : await checksApi.create(values.subject, checkCreatePayload(form, values.requiresColumn))
                    // Defaults come from the saved row before closing, so a clean form never trips
                    // the discard confirmation on the way out.
                    actions.resetCheckForm(checkToForm(saved))
                    actions.closeEditor()
                    props.onSaved?.(saved)
                    lemonToast.success('Check saved', {
                        button: { label: 'Run now', action: () => props.onRunNow?.(saved) },
                    })
                } catch (error) {
                    const fieldErrors = serverFieldErrors(error, form.checkType)
                    if (Object.keys(fieldErrors).length) {
                        actions.setCheckFormManualErrors(fieldErrors)
                    } else {
                        actions.setServerError(generalErrorMessage(error))
                    }
                    throw error
                } finally {
                    cache.savingCheck = false
                }
            },
        },
    })),
    selectors({
        customSqlSourceQuery: [
            (s) => [s.checkForm],
            (checkForm: CheckFormValues): HogQLQuery => ({ kind: NodeKind.HogQLQuery, query: checkForm.customSql }),
        ],
        customSqlPreviewStale: [
            (s) => [s.customSqlPreview, s.checkForm],
            (customSqlPreview: CustomSqlPreview | null, checkForm: CheckFormValues) =>
                !!customSqlPreview && customSqlPreview.sql !== checkForm.customSql.trim(),
        ],
        customSqlPreviewVerdict: [
            (s) => [s.customSqlPreview],
            (customSqlPreview: CustomSqlPreview | null) =>
                customSqlPreview ? (customSqlPreview.rowCount === 0 ? 'pass' : 'fail') : null,
        ],
        requiresColumn: [
            (s) => [s.checkForm, s.checkTypeByName],
            (checkForm: CheckFormValues, checkTypeByName: Record<string, DataQualityCheckTypeApi>) =>
                !!checkTypeByName[checkForm.checkType]?.requires_column,
        ],
        needsWarehouseCatalog: [
            (s) => [s.checkForm, s.requiresColumn, s.subjectColumns, s.subject],
            (
                checkForm: CheckFormValues,
                requiresColumn: boolean,
                subjectColumns: string[],
                subject: DataQualitySubjectRef | null
            ) =>
                // Relationships needs every subject to point at; anything else only needs the
                // catalog when the surface that opened the editor could not supply the columns.
                subject === null ||
                checkForm.checkType === CheckTypeEnumApi.Relationships ||
                (requiresColumn && !subjectColumns.length),
        ],
    }),
    listeners(({ props, values, actions }) => {
        const ensureWarehouseCatalog = (): void => {
            if (values.warehouseCatalogRequested || !values.needsWarehouseCatalog) {
                return
            }
            actions.loadWarehouseCatalog()
        }

        return {
            openEditor: ({ check, subject }) => {
                actions.resetCheckForm(
                    check
                        ? checkToForm(check)
                        : subject?.subjectType === 'metric'
                          ? {
                                ...EMPTY_CHECK_FORM,
                                checkType: CheckTypeEnumApi.CustomSql,
                                customSql: METRIC_CHECK_QUERY_TEMPLATE,
                            }
                          : EMPTY_CHECK_FORM
                )
                actions.loadCheckTypes()
                if (subject?.subjectType === SubjectTypeEnumApi.Metric) {
                    actions.loadMetricOutputSchema(undefined)
                }
                if (subject === null) {
                    actions.loadMetricSubjects()
                }
                ensureWarehouseCatalog()
            },
            setSubject: ({ subject }) => {
                actions.resetCheckForm(
                    subject.subjectType === SubjectTypeEnumApi.Metric
                        ? {
                              ...EMPTY_CHECK_FORM,
                              checkType: CheckTypeEnumApi.CustomSql,
                              customSql: METRIC_CHECK_QUERY_TEMPLATE,
                          }
                        : EMPTY_CHECK_FORM
                )
                actions.loadCheckTypes()
                if (subject.subjectType === SubjectTypeEnumApi.Metric) {
                    actions.loadMetricOutputSchema(undefined)
                }
                actions.setServerError(null)
                actions.setCheckFormManualErrors({})
            },
            setCheckFormValues: () => {
                if (values.isOpen) {
                    ensureWarehouseCatalog()
                }
            },
            loadWarehouseCatalog: () => {
                actions.loadDatabase()
            },
            requestClose: () => {
                if (!values.checkFormChanged) {
                    actions.closeEditor()
                    return
                }
                LemonDialog.open({
                    title: 'Discard changes?',
                    description: 'Your unsaved changes will be lost.',
                    primaryButton: {
                        children: 'Discard changes',
                        status: 'danger',
                        onClick: () => actions.closeEditor(),
                    },
                    secondaryButton: { children: 'Keep editing' },
                })
            },
            closeEditor: () => {
                props.onClosed?.()
            },
        }
    }),
])
