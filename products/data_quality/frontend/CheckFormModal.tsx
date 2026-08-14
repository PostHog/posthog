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
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { checkTypeLabel } from './checksConstants'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import { CheckTypeEnumApi, DataQualityCheckSeverityEnumApi, SubjectTypeEnumApi } from './generated/api.schemas'

const EDIT_LOCK_REASON = "A check's assertion can't be edited. Create a new check instead."

interface CheckFormModalProps extends DataQualityChecksLogicProps {
    columns: DatabaseSchemaField[]
}

export function CheckFormModal({ columns, ...logicProps }: CheckFormModalProps): JSX.Element {
    const logic = dataQualityChecksLogic(logicProps)
    const { checkModalOpen, editingCheck, checkForm, checkTypes, checkTypeByName, isCheckFormSubmitting, serverError } =
        useValues(logic)
    const { closeCheckModal, submitCheckForm, setCheckFormValues } = useActions(logic)

    const isEditing = !!editingCheck
    const editLockReason = isEditing ? EDIT_LOCK_REASON : undefined
    const requiresColumn = !!checkTypeByName[checkForm.checkType]?.requires_column

    return (
        <LemonModal
            isOpen={checkModalOpen}
            onClose={closeCheckModal}
            title={isEditing ? 'Edit check' : 'New check'}
            width={640}
            footer={
                <div className="flex flex-col items-end gap-2 w-full">
                    {serverError && <span className="text-danger text-sm">{serverError}</span>}
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeCheckModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitCheckForm}
                            loading={isCheckFormSubmitting}
                            data-attr="data-quality-check-save"
                        >
                            Save check
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <Form logic={dataQualityChecksLogic} props={logicProps} formKey="checkForm" className="flex flex-col gap-3">
                <LemonField name="checkType" label="Check type">
                    <LemonSelect
                        disabledReason={editLockReason}
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
                            disabledReason={editLockReason}
                            options={columns.map((column) => ({ value: column.name, label: column.name }))}
                        />
                    </LemonField>
                )}

                <CheckConfigFields
                    checkType={checkForm.checkType}
                    disabledReason={editLockReason}
                    logicProps={logicProps}
                />

                <LemonField name="name" label="Name" showOptional>
                    <LemonInput placeholder="orders_customer_id_not_null" />
                </LemonField>

                <LemonField name="description" label="Description" showOptional>
                    <LemonTextArea placeholder="Why this check exists and what a failure means" minRows={2} />
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

function CheckConfigFields({
    checkType,
    disabledReason,
    logicProps,
}: {
    checkType: CheckTypeEnumApi
    disabledReason?: string
    logicProps: DataQualityChecksLogicProps
}): JSX.Element | null {
    switch (checkType) {
        case CheckTypeEnumApi.AcceptedValues:
            return (
                <LemonField name="acceptedValues" label="Allowed values">
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        options={[]}
                        disabled={!!disabledReason}
                        placeholder="Add a value"
                    />
                </LemonField>
            )
        case CheckTypeEnumApi.Relationships:
            return <RelationshipFields disabledReason={disabledReason} logicProps={logicProps} />
        case CheckTypeEnumApi.RowCount:
            return (
                <div className="flex gap-3">
                    <LemonField name="rowCountMin" label="Minimum rows" showOptional className="flex-1">
                        <LemonInput type="number" min={0} disabled={!!disabledReason} />
                    </LemonField>
                    <LemonField name="rowCountMax" label="Maximum rows" showOptional className="flex-1">
                        <LemonInput type="number" min={0} disabled={!!disabledReason} />
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
                    <LemonInput type="number" min={1} disabled={!!disabledReason} />
                </LemonField>
            )
        case CheckTypeEnumApi.CustomSql:
            return (
                <LemonField
                    name="customSql"
                    label="Query"
                    help="Return one row per failure. The check passes when the query returns nothing."
                >
                    {({ value, onChange }) => (
                        <CodeEditorResizeable
                            language="hogQL"
                            value={value ?? ''}
                            onChange={(query) => onChange(query ?? '')}
                            minHeight="8rem"
                            maxHeight="40vh"
                            options={{ readOnly: !!disabledReason }}
                        />
                    )}
                </LemonField>
            )
        default:
            return null
    }
}

function RelationshipFields({
    disabledReason,
    logicProps,
}: {
    disabledReason?: string
    logicProps: DataQualityChecksLogicProps
}): JSX.Element {
    const { checkForm } = useValues(dataQualityChecksLogic(logicProps))
    const { setCheckFormValues } = useActions(dataQualityChecksLogic(logicProps))
    const { dataWarehouseTables, views } = useValues(databaseTableListLogic)

    // Only warehouse subjects carry the uuid a relationships check references; PostHog-native and
    // system tables have no check subject to point at.
    const subjects = [
        ...views.map((view) => ({ id: view.id, name: view.name, type: SubjectTypeEnumApi.View, fields: view.fields })),
        ...dataWarehouseTables.map((table) => ({
            id: table.id,
            name: table.name,
            type: SubjectTypeEnumApi.Table,
            fields: table.fields,
        })),
    ].filter((subject) => !!subject.id)

    const selected = subjects.find((subject) => subject.id === checkForm.toSubjectUuid)

    return (
        <>
            <LemonField name="toSubjectUuid" label="References table or view">
                <LemonSelect
                    disabledReason={disabledReason}
                    options={subjects.map((subject) => ({ value: subject.id, label: subject.name }))}
                    onChange={(toSubjectUuid) =>
                        setCheckFormValues({
                            toSubjectUuid,
                            toSubjectType: subjects.find((subject) => subject.id === toSubjectUuid)?.type,
                            toColumn: '',
                        })
                    }
                />
            </LemonField>
            <LemonField name="toColumn" label="References column">
                <LemonSelect
                    disabledReason={disabledReason ?? (selected ? undefined : 'Pick a table or view first')}
                    options={Object.keys(selected?.fields ?? {}).map((field) => ({ value: field, label: field }))}
                />
            </LemonField>
        </>
    )
}
