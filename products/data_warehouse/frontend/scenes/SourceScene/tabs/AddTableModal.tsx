import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AddTableFileFormat, addTableLogic } from './addTableLogic'
import { sourceSettingsLogic } from './sourceSettingsLogic'

const FILE_FORMAT_OPTIONS: { value: AddTableFileFormat; label: string }[] = [
    { value: 'infer', label: 'Detect from file names' },
    { value: 'parquet', label: 'Parquet' },
    { value: 'csv', label: 'CSV with header' },
    { value: 'csv_no_header', label: 'CSV without header' },
    { value: 'jsonl', label: 'JSON lines' },
    { value: 'delta', label: 'Delta Lake' },
]

export function AddTableModal({ sourceId }: { sourceId: string }): JSX.Element {
    const logic = addTableLogic({ sourceId })
    const { isAddTableOpen, isAddTableSubmitting, addTable } = useValues(logic)
    const { closeAddTable, editName, submitAddTable } = useActions(logic)
    const { source } = useValues(sourceSettingsLogic({ id: sourceId }))

    const root = source?.table_root
    const description = root
        ? `Enter a path inside ${root}. You can also paste the full URL of the files.`
        : 'Enter a path inside your bucket. You can also paste the full URL of the files.'
    const isCsv = addTable.file_format === 'csv' || addTable.file_format === 'csv_no_header'

    return (
        <LemonModal
            isOpen={isAddTableOpen}
            onClose={isAddTableSubmitting ? undefined : closeAddTable}
            closable={!isAddTableSubmitting}
            title="Add table"
            description={description}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeAddTable}
                        disabledReason={isAddTableSubmitting ? 'The table is being added' : undefined}
                        data-attr="add-table-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitAddTable}
                        loading={isAddTableSubmitting}
                        data-attr="add-table-submit"
                    >
                        Add table
                    </LemonButton>
                </>
            }
        >
            <Form logic={addTableLogic} props={{ sourceId }} formKey="addTable" enableFormOnSubmit>
                <div className="flex flex-col gap-3">
                    <LemonField
                        name="path"
                        label="Path"
                        help="A folder imports every file in it and its subfolders. Wildcards such as *, ** and {a,b} also work."
                    >
                        <LemonInput placeholder="events/2026/*.parquet" data-attr="add-table-path" autoFocus />
                    </LemonField>
                    <LemonField name="file_format" label="File format">
                        <LemonSelect options={FILE_FORMAT_OPTIONS} fullWidth data-attr="add-table-format" />
                    </LemonField>
                    {isCsv && (
                        <LemonField name="csv_allow_double_quotes">
                            {({ value, onChange }) => (
                                <LemonCheckbox
                                    label="Allow double quotes inside quoted CSV values"
                                    checked={!!value}
                                    onChange={onChange}
                                    data-attr="add-table-csv-double-quotes"
                                />
                            )}
                        </LemonField>
                    )}
                    <LemonField name="name" label="Table name">
                        {({ value, error }) => (
                            <LemonInput
                                value={value}
                                onChange={editName}
                                status={error ? 'danger' : 'default'}
                                placeholder="events"
                                data-attr="add-table-name"
                            />
                        )}
                    </LemonField>
                    <LemonField name="start_syncing">
                        {({ value, onChange }) => (
                            <LemonCheckbox
                                label="Start syncing after adding"
                                checked={!!value}
                                onChange={onChange}
                                data-attr="add-table-start-syncing"
                            />
                        )}
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}
