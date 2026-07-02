import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonModal, LemonSearchableSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'

export function CustomPropertySourceModal(): JSX.Element {
    const {
        sourceModalVisible,
        sourceDefinition,
        customPropertySourceForm,
        isCustomPropertySourceFormSubmitting,
        materializedViews,
        selectedSourceColumns,
        savedQueriesLoading,
        definitionsLoading,
    } = useValues(customPropertyDefinitionsLogic)
    const { closeSourceModal, submitCustomPropertySourceForm, removeSource, setCustomPropertySourceFormValue } =
        useActions(customPropertyDefinitionsLogic)

    const editing = !!sourceDefinition?.source
    const noViews = !savedQueriesLoading && materializedViews.length === 0

    return (
        <LemonModal
            isOpen={sourceModalVisible}
            onClose={closeSourceModal}
            title={`Sync “${sourceDefinition?.name ?? ''}” from a view`}
            description="Pull this property's values from a materialized view column on each materialization, matched to accounts by external ID."
            footer={
                <div className="flex justify-between items-center w-full">
                    <div>
                        {editing && sourceDefinition && (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={() => removeSource({ definition: sourceDefinition })}
                                loading={definitionsLoading}
                            >
                                Remove sync
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeSourceModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitCustomPropertySourceForm}
                            loading={isCustomPropertySourceFormSubmitting}
                            disabledReason={noViews ? 'No materialized views are available' : undefined}
                        >
                            {editing ? 'Save' : 'Configure sync'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            {noViews ? (
                <LemonBanner type="info">
                    No materialized views found. Create and materialize a view in the data warehouse first, then it can
                    feed this property.
                </LemonBanner>
            ) : (
                <Form
                    logic={customPropertyDefinitionsLogic}
                    formKey="customPropertySourceForm"
                    enableFormOnSubmit
                    className="flex flex-col gap-4"
                >
                    <LemonField name="savedQuery" label="View">
                        {({ value, onChange }) => (
                            <LemonSearchableSelect
                                value={value}
                                onChange={(newValue) => {
                                    onChange(newValue)
                                    // Columns are view-specific, so a view change invalidates the picks.
                                    setCustomPropertySourceFormValue('sourceColumn', null)
                                    setCustomPropertySourceFormValue('keyColumn', null)
                                }}
                                options={materializedViews.map((view) => ({ value: view.id, label: view.name }))}
                                loading={savedQueriesLoading}
                                disabledReason={editing ? 'The view is fixed once a sync is created' : undefined}
                                placeholder="Select a materialized view"
                                fullWidth
                            />
                        )}
                    </LemonField>
                    <LemonField
                        name="sourceColumn"
                        label="Value column"
                        help="The column whose value is written to this property."
                    >
                        {({ value, onChange }) => (
                            <LemonSearchableSelect
                                value={value}
                                onChange={onChange}
                                options={selectedSourceColumns.map((column) => ({ value: column, label: column }))}
                                loading={savedQueriesLoading}
                                disabledReason={
                                    !customPropertySourceForm.savedQuery ? 'Select a view first' : undefined
                                }
                                placeholder="Column to read the value from"
                                fullWidth
                            />
                        )}
                    </LemonField>
                    <LemonField
                        name="keyColumn"
                        label="Key column"
                        help="The column matched against each account's external ID."
                    >
                        {({ value, onChange }) => (
                            <LemonSearchableSelect
                                value={value}
                                onChange={onChange}
                                options={selectedSourceColumns.map((column) => ({ value: column, label: column }))}
                                loading={savedQueriesLoading}
                                disabledReason={
                                    !customPropertySourceForm.savedQuery ? 'Select a view first' : undefined
                                }
                                placeholder="Column matching the account external ID"
                                fullWidth
                            />
                        )}
                    </LemonField>
                    <LemonField name="isEnabled">
                        {({ value, onChange }) => (
                            <LemonSwitch checked={value} onChange={onChange} label="Sync enabled" bordered />
                        )}
                    </LemonField>
                </Form>
            )}
        </LemonModal>
    )
}
