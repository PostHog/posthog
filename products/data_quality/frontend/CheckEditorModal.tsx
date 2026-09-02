import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
    LemonTextArea,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { urls } from 'scenes/urls'

import type { DataQualitySubjectRef } from './checksApi'
import { checkTypeLabel } from './checksConstants'
import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { CheckTypeEnumApi, DataQualityCheckSeverityEnumApi, SubjectTypeEnumApi } from './generated/api.schemas'
import { formatPreviewCell } from './previewCell'

export function CheckEditorModal(): JSX.Element {
    const {
        isOpen,
        editingCheck,
        checkForm,
        checkTypes,
        checkTypesError,
        checkTypesLoading,
        requiresColumn,
        availableColumns,
        databaseLoading,
        databaseLoadError,
        openedWithoutSubject,
        relationshipSubjects,
        subject,
        isCheckFormSubmitting,
        serverError,
    } = useValues(dataQualityCheckEditorLogic)
    // Which fields the form has depends on the check-type catalog, so showing the form before it
    // arrives means fields appearing under the user's cursor a moment later.
    const formShapeLoading = checkTypesLoading && !checkTypes.length
    const awaitingSubject = openedWithoutSubject && !subject
    const checkTypesFailedEmpty = checkTypesError && !checkTypesLoading && !checkTypes.length
    const { loadCheckTypes, loadDatabase, requestClose, setCheckFormValues, setSubject, submitCheckForm } =
        useActions(dataQualityCheckEditorLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={requestClose}
            title={editingCheck ? 'Edit check' : 'New check'}
            width={640}
            footer={
                <div className="flex flex-col items-end gap-2 w-full">
                    {serverError && <span className="text-danger text-sm">{serverError}</span>}
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={requestClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitCheckForm}
                            loading={isCheckFormSubmitting}
                            disabledReason={
                                awaitingSubject
                                    ? 'Pick a table or view first'
                                    : isCheckFormSubmitting
                                      ? 'Saving'
                                      : formShapeLoading
                                        ? 'Loading the check types'
                                        : checkTypesFailedEmpty
                                          ? 'Load the check types to continue'
                                          : undefined
                            }
                            data-attr="data-quality-check-save"
                        >
                            Save check
                        </LemonButton>
                    </div>
                </div>
            }
        >
            {formShapeLoading && (
                <div className="flex items-center gap-2 py-8 justify-center text-secondary">
                    <Spinner className="text-xl" />
                    <span>Loading check types...</span>
                </div>
            )}
            {openedWithoutSubject && (
                <div className="flex flex-col gap-2 mb-3">
                    <LemonField.Pure label="Table or view">
                        <LemonInputSelect
                            mode="single"
                            value={subject ? [subject.subjectId] : []}
                            options={relationshipSubjects.map((candidate) => ({
                                key: candidate.id,
                                label: candidate.name,
                            }))}
                            onChange={(selectedIds) => {
                                const selected = relationshipSubjects.find(
                                    (candidate) => candidate.id === selectedIds[0]
                                )
                                if (!selected) {
                                    return
                                }
                                const selectedSubject: DataQualitySubjectRef = {
                                    subjectId: selected.id,
                                    subjectType: selected.type === SubjectTypeEnumApi.View ? 'view' : 'table',
                                }
                                setSubject(selectedSubject)
                            }}
                            loading={databaseLoading}
                            placeholder="Search tables and views"
                            data-attr="data-quality-check-subject"
                        />
                    </LemonField.Pure>
                    {databaseLoadError && !databaseLoading ? (
                        <div className="flex items-center gap-2 text-secondary text-sm">
                            <span>Couldn't load your tables and views.</span>
                            <LemonButton size="small" type="secondary" onClick={() => loadDatabase()}>
                                Retry
                            </LemonButton>
                        </div>
                    ) : !databaseLoading && relationshipSubjects.length === 0 ? (
                        <p className="mb-0 text-secondary text-sm">
                            Connect a source or <Link to={urls.database()}>browse tables and views</Link>.
                        </p>
                    ) : null}
                </div>
            )}
            {checkTypesFailedEmpty && (
                <div className="flex items-center gap-2 py-8 justify-center text-secondary">
                    <span>Couldn't load check types.</span>
                    <LemonButton size="small" type="secondary" onClick={loadCheckTypes}>
                        Retry
                    </LemonButton>
                </div>
            )}
            <Form
                logic={dataQualityCheckEditorLogic}
                formKey="checkForm"
                className={
                    formShapeLoading || awaitingSubject || checkTypesFailedEmpty ? 'hidden' : 'flex flex-col gap-3'
                }
            >
                <LemonField name="checkType" label="Check type">
                    <LemonSelect
                        options={checkTypes.map((checkType) => ({
                            value: checkType.check_type as CheckTypeEnumApi,
                            label: checkTypeLabel(checkType.check_type),
                            labelInMenu: (
                                <div className="flex flex-col">
                                    <span>{checkTypeLabel(checkType.check_type)}</span>
                                    <span className="text-secondary text-xs">{checkType.description}</span>
                                </div>
                            ),
                        }))}
                        onChange={(checkType) =>
                            // The config fields belong to the type that was selected, so they can't carry over.
                            setCheckFormValues({
                                checkType,
                                columnName: '',
                                acceptedValues: [],
                                toSubjectUuid: '',
                                toColumn: '',
                                rowCountMin: null,
                                rowCountMax: null,
                                maxAgeMinutes: null,
                                customSql: '',
                            })
                        }
                    />
                </LemonField>

                {requiresColumn && (
                    <LemonField name="columnName" label="Column">
                        <LemonSelect
                            loading={databaseLoading && !availableColumns.length}
                            options={availableColumns.map((column) => ({ value: column, label: column }))}
                        />
                    </LemonField>
                )}

                <CheckConfigFields checkType={checkForm.checkType} />

                <LemonField
                    name="name"
                    label="Name"
                    showOptional
                    help="Lets you refer to this check by name in SQL and the API instead of by its id. Letters, numbers and underscores, starting with a letter."
                >
                    <LemonInput placeholder="orders_customer_id_not_null" />
                </LemonField>

                <LemonField
                    name="description"
                    label="Description"
                    showOptional
                    help="Why this check exists and what a failure means. Shown to whoever finds the check failing."
                >
                    <LemonTextArea placeholder="Every order has to belong to a customer" minRows={2} />
                </LemonField>

                <LemonField name="severity" label="Severity">
                    <LemonSegmentedButton
                        options={[
                            { value: DataQualityCheckSeverityEnumApi.Error, label: 'Error' },
                            { value: DataQualityCheckSeverityEnumApi.Warn, label: 'Warning' },
                        ]}
                    />
                </LemonField>

                <LemonField name="tags" label="Tags" showOptional>
                    <LemonInputSelect mode="multiple" allowCustomValues options={[]} placeholder="Add a tag" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}

function CheckConfigFields({ checkType }: { checkType: CheckTypeEnumApi }): JSX.Element | null {
    switch (checkType) {
        case CheckTypeEnumApi.AcceptedValues:
            return (
                <LemonField name="acceptedValues" label="Allowed values">
                    <LemonInputSelect mode="multiple" allowCustomValues options={[]} placeholder="Add a value" />
                </LemonField>
            )
        case CheckTypeEnumApi.Relationships:
            return <RelationshipFields />
        case CheckTypeEnumApi.RowCount:
            return (
                <div className="flex gap-3">
                    <LemonField name="rowCountMin" label="Minimum rows" showOptional className="flex-1">
                        <LemonInput type="number" min={0} />
                    </LemonField>
                    <LemonField name="rowCountMax" label="Maximum rows" showOptional className="flex-1">
                        <LemonInput type="number" min={0} />
                    </LemonField>
                </div>
            )
        case CheckTypeEnumApi.Freshness:
            return (
                <LemonField
                    name="maxAgeMinutes"
                    label="Maximum age in minutes"
                    help="The check fails when the newest value in the column is older than this."
                >
                    <LemonInput type="number" min={1} />
                </LemonField>
            )
        case CheckTypeEnumApi.CustomSql:
            return <CustomSqlField />
        default:
            return null
    }
}

function CustomSqlField(): JSX.Element {
    const {
        customSqlEditorError,
        customSqlPreview,
        customSqlPreviewError,
        customSqlPreviewLoading,
        customSqlPreviewStale,
        customSqlPreviewVerdict,
        customSqlQueryKey,
        customSqlSourceQuery,
    } = useValues(dataQualityCheckEditorLogic)
    const { runCustomSqlPreview, setCustomSqlEditorError, setCustomSqlValidationLoading } =
        useActions(dataQualityCheckEditorLogic)

    const previewRows = customSqlPreview?.rows ?? []
    // Key and index by position, not by column name: HogQL can return two columns with the same name
    // (e.g. `SELECT id, id`), which would collide on an object key and on the React header key.
    const previewColumns: LemonTableColumns<unknown[]> =
        customSqlPreview?.columns.map((column, index) => ({
            title: column,
            key: String(index),
            dataIndex: index,
            // Never hand a raw object to LemonTable: it would spread the value's `props` onto the cell.
            render: (value: unknown) => formatPreviewCell(value),
        })) ?? []

    return (
        <LemonField
            name="customSql"
            label="Query"
            help="Return one row per failure. The check passes when the query returns nothing."
        >
            {({ value, onChange }) => (
                <div className="flex flex-col gap-2">
                    <CodeEditorResizeable
                        language="hogQL"
                        value={value ?? ''}
                        onChange={(query) => onChange(query ?? '')}
                        queryKey={customSqlQueryKey}
                        sourceQuery={customSqlSourceQuery}
                        onError={setCustomSqlEditorError}
                        onMetadataLoading={setCustomSqlValidationLoading}
                        onPressCmdEnter={() => runCustomSqlPreview(undefined)}
                        autoFocus
                        minHeight="8rem"
                        maxHeight="40vh"
                    />
                    <div className="flex flex-col items-end gap-1">
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={customSqlPreviewLoading}
                            disabledReason={
                                !value?.trim()
                                    ? 'Write a query before testing it.'
                                    : (customSqlEditorError ?? undefined)
                            }
                            onClick={runCustomSqlPreview}
                            data-attr="data-quality-check-test-query"
                        >
                            Test query
                        </LemonButton>
                        {customSqlPreviewStale && (
                            <span className="text-secondary text-xs">The query changed since the last test.</span>
                        )}
                    </div>
                    {customSqlPreviewError ? (
                        <LemonBanner type="error">{customSqlPreviewError}</LemonBanner>
                    ) : !customSqlPreviewLoading && customSqlPreview && customSqlPreviewVerdict ? (
                        <div className={customSqlPreviewStale ? 'opacity-60' : undefined}>
                            {customSqlPreview.warnings.length > 0 && (
                                <LemonBanner type="warning" className="mb-2">
                                    This result may be incomplete or out of date:
                                    <ul className="list-disc pl-5">
                                        {customSqlPreview.warnings.map((warning, index) => (
                                            <li key={index}>{warning.message}</li>
                                        ))}
                                    </ul>
                                </LemonBanner>
                            )}
                            {customSqlPreviewVerdict === 'pass' ? (
                                <LemonBanner type="success">
                                    The query returned no rows. This check would pass.
                                </LemonBanner>
                            ) : (
                                <>
                                    <LemonBanner type="warning">
                                        The query returned {customSqlPreview.hasMore ? 'at least ' : ''}
                                        {customSqlPreview.rowCount} rows. This check would fail with{' '}
                                        {customSqlPreview.hasMore ? 'at least ' : ''}
                                        {customSqlPreview.rowCount} failures.
                                    </LemonBanner>
                                    <LemonTable<unknown[]>
                                        className="mt-2"
                                        columns={previewColumns}
                                        dataSource={previewRows}
                                        size="small"
                                    />
                                    {/* The table caps at 10 rows: flag truncation only when 10 are shown and the
                                        response held more, or the query system reported more beyond them. */}
                                    {previewRows.length === 10 &&
                                        (customSqlPreview.hasMore ||
                                            customSqlPreview.rowCount > previewRows.length) && (
                                            <span className="mt-1 text-secondary text-xs">
                                                Showing the first 10 rows.
                                            </span>
                                        )}
                                </>
                            )}
                        </div>
                    ) : null}
                </div>
            )}
        </LemonField>
    )
}

function RelationshipFields(): JSX.Element {
    const { checkForm, relationshipSubjects, databaseLoading } = useValues(dataQualityCheckEditorLogic)
    const { setCheckFormValues } = useActions(dataQualityCheckEditorLogic)

    const selected = relationshipSubjects.find((subject) => subject.id === checkForm.toSubjectUuid)

    return (
        <>
            <LemonField name="toSubjectUuid" label="References table or view">
                <LemonInputSelect
                    mode="single"
                    loading={databaseLoading}
                    value={checkForm.toSubjectUuid ? [checkForm.toSubjectUuid] : []}
                    options={relationshipSubjects.map((subject) => ({ key: subject.id, label: subject.name }))}
                    onChange={(selectedIds) => {
                        const toSubjectUuid = selectedIds[0]
                        if (!toSubjectUuid) {
                            return
                        }
                        setCheckFormValues({
                            toSubjectUuid,
                            toSubjectType: relationshipSubjects.find((subject) => subject.id === toSubjectUuid)?.type,
                            toColumn: '',
                        })
                    }}
                />
            </LemonField>
            <LemonField name="toColumn" label="References column">
                <LemonSelect
                    disabledReason={selected ? undefined : 'Pick a table or view first'}
                    options={(selected?.fields ?? []).map((field) => ({ value: field, label: field }))}
                />
            </LemonField>
        </>
    )
}
