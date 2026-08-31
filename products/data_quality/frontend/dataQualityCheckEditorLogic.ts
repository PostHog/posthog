import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import type {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaViewTable,
} from '../../../frontend/src/queries/schema/schema-general'
import { DataQualitySubjectRef, checksApi } from './checksApi'
import type { DataQualityCheckApi, DataQualityCheckTypeApi } from './generated/api.schemas'
import { CheckTypeEnumApi, DataQualityCheckSeverityEnumApi, SubjectTypeEnumApi } from './generated/api.schemas'

const CHECK_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]*$/

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

export function checkEditPayload(form: CheckFormValues, requiresColumn: boolean): CheckEditPayload {
    return {
        ...definitionPayload(form, requiresColumn),
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
    databaseLoading: boolean // databaseTableListLogic
    views: DatabaseSchemaViewTable[] // databaseTableListLogic
    availableColumns: string[]
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
    checkTypesLoading: boolean
    editingCheck: DataQualityCheckApi | null
    isCheckFormSubmitting: boolean
    isCheckFormValid: boolean
    isOpen: boolean
    needsWarehouseCatalog: boolean
    relationshipSubjects: RelationshipSubject[]
    requiresColumn: boolean
    serverError: string | null
    showCheckFormErrors: boolean
    subject: DataQualitySubjectRef | null
    subjectColumns: string[]
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
    loadWarehouseCatalog: () => {
        value: true
    }
    openEditor: (
        check: DataQualityCheckApi | null,
        subject: DataQualitySubjectRef,
        columns?: string[]
    ) => {
        check: DataQualityCheckApi | null
        columns: string[]
        subject: DataQualitySubjectRef
    }
    requestClose: () => {
        value: true
    }
    resetCheckForm: (values?: CheckFormValues) => {
        values?: CheckFormValues
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
    setServerError: (serverError: string | null) => {
        serverError: string | null
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
        checkTypeByName: (checkTypes: DataQualityCheckTypeApi[]) => {
            [k: string]: DataQualityCheckTypeApi
        }
        relationshipSubjects: (
            views: DatabaseSchemaViewTable[],
            dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
        ) => RelationshipSubject[]
        availableColumns: (
            subjectColumns: string[],
            subject: DataQualitySubjectRef | null,
            relationshipSubjects: RelationshipSubject[]
        ) => string[]
        requiresColumn: (
            checkForm: CheckFormValues,
            checkTypeByName: {
                [k: string]: DataQualityCheckTypeApi
            }
        ) => boolean
        needsWarehouseCatalog: (
            checkForm: CheckFormValues,
            requiresColumn: boolean,
            subjectColumns: string[]
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
        values: [databaseTableListLogic, ['views', 'dataWarehouseTables', 'databaseLoading']],
    })),
    actions({
        openEditor: (check: DataQualityCheckApi | null, subject: DataQualitySubjectRef, columns: string[] = []) => ({
            check,
            subject,
            columns,
        }),
        requestClose: true,
        closeEditor: true,
        setServerError: (serverError: string | null) => ({ serverError }),
        loadWarehouseCatalog: true,
    }),
    loaders(({ values }) => ({
        checkTypes: [
            [] as DataQualityCheckTypeApi[],
            {
                loadCheckTypes: async () =>
                    values.subject ? await checksApi.checkTypes(values.subject) : values.checkTypes,
            },
        ],
    })),
    reducers({
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
            },
        ],
        subjectColumns: [
            [] as string[],
            {
                openEditor: (_, { columns }) => columns,
            },
        ],
        // One request per editor instance: a type switch back to relationships must not refetch.
        warehouseCatalogRequested: [
            false,
            {
                loadWarehouseCatalog: () => true,
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
    }),
    selectors({
        checkTypeByName: [
            (s) => [s.checkTypes],
            (checkTypes: DataQualityCheckTypeApi[]) =>
                Object.fromEntries(checkTypes.map((checkType) => [checkType.check_type, checkType])),
        ],
        relationshipSubjects: [
            (s) => [s.views, s.dataWarehouseTables],
            (views: any[], dataWarehouseTables: any[]): RelationshipSubject[] =>
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
                    })),
        ],
        availableColumns: [
            (s) => [s.subjectColumns, s.subject, s.relationshipSubjects],
            (
                subjectColumns: string[],
                subject: DataQualitySubjectRef | null,
                relationshipSubjects: RelationshipSubject[]
            ) =>
                subjectColumns.length
                    ? subjectColumns
                    : (relationshipSubjects.find((candidate) => candidate.id === subject?.subjectId)?.fields ?? []),
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
                              checkEditPayload(form, values.requiresColumn)
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
        requiresColumn: [
            (s) => [s.checkForm, s.checkTypeByName],
            (checkForm: CheckFormValues, checkTypeByName: Record<string, DataQualityCheckTypeApi>) =>
                !!checkTypeByName[checkForm.checkType]?.requires_column,
        ],
        needsWarehouseCatalog: [
            (s) => [s.checkForm, s.requiresColumn, s.subjectColumns],
            (checkForm: CheckFormValues, requiresColumn: boolean, subjectColumns: string[]) =>
                // Relationships needs every subject to point at; anything else only needs the
                // catalog when the surface that opened the editor could not supply the columns.
                checkForm.checkType === CheckTypeEnumApi.Relationships || (requiresColumn && !subjectColumns.length),
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
            openEditor: ({ check }) => {
                actions.resetCheckForm(check ? checkToForm(check) : EMPTY_CHECK_FORM)
                if (!values.checkTypes.length) {
                    actions.loadCheckTypes()
                }
                ensureWarehouseCatalog()
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
