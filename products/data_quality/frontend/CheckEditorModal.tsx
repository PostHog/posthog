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
    Spinner,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { checkTypeLabel } from './checksConstants'
import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { CheckTypeEnumApi, DataQualityCheckSeverityEnumApi } from './generated/api.schemas'

export function CheckEditorModal(): JSX.Element {
    const {
        isOpen,
        editingCheck,
        checkForm,
        checkTypes,
        checkTypesLoading,
        requiresColumn,
        availableColumns,
        databaseLoading,
        isCheckFormSubmitting,
        serverError,
    } = useValues(dataQualityCheckEditorLogic)
    // Which fields the form has depends on the check-type catalog, so showing the form before it
    // arrives means fields appearing under the user's cursor a moment later.
    const formShapeLoading = checkTypesLoading && !checkTypes.length
    const { requestClose, submitCheckForm, setCheckFormValues } = useActions(dataQualityCheckEditorLogic)

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
                                isCheckFormSubmitting
                                    ? 'Saving'
                                    : formShapeLoading
                                      ? 'Loading the check types'
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
            <Form
                logic={dataQualityCheckEditorLogic}
                formKey="checkForm"
                className={formShapeLoading ? 'hidden' : 'flex flex-col gap-3'}
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
                        />
                    )}
                </LemonField>
            )
        default:
            return null
    }
}

function RelationshipFields(): JSX.Element {
    const { checkForm, relationshipSubjects, databaseLoading } = useValues(dataQualityCheckEditorLogic)
    const { setCheckFormValues } = useActions(dataQualityCheckEditorLogic)

    const selected = relationshipSubjects.find((subject) => subject.id === checkForm.toSubjectUuid)

    return (
        <>
            <LemonField name="toSubjectUuid" label="References table or view">
                <LemonSelect
                    loading={databaseLoading}
                    options={relationshipSubjects.map((subject) => ({ value: subject.id, label: subject.name }))}
                    onChange={(toSubjectUuid) =>
                        setCheckFormValues({
                            toSubjectUuid,
                            toSubjectType: relationshipSubjects.find((subject) => subject.id === toSubjectUuid)?.type,
                            toColumn: '',
                        })
                    }
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
