import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSearchableSelect,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import { CustomPropertySourceMode, customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { DISPLAY_TYPE_OPTIONS, isNumericDisplayType } from './customPropertyTypes'

const SOURCE_MODE_OPTIONS: { value: CustomPropertySourceMode; label: string }[] = [
    { value: 'manual', label: 'Manual' },
    { value: 'data_warehouse', label: 'Data warehouse' },
]

export function CustomPropertyModal(): JSX.Element {
    const {
        modalVisible,
        editingDefinition,
        customPropertyForm,
        isCustomPropertyFormSubmitting,
        materializedViews,
        selectedSourceColumns,
        savedQueriesLoading,
    } = useValues(customPropertyDefinitionsLogic)
    const { closeModal, submitCustomPropertyForm, setCustomPropertyFormValue } =
        useActions(customPropertyDefinitionsLogic)

    const showBigNumberSwitch = isNumericDisplayType(customPropertyForm.displayType)
    const { sourceMode } = customPropertyForm
    const hasExistingSource = !!editingDefinition?.source
    const noViews = !savedQueriesLoading && materializedViews.length === 0

    const submitDisabledReason =
        sourceMode === 'data_warehouse' && noViews ? 'No materialized views are available' : undefined

    return (
        <LemonModal
            isOpen={modalVisible}
            onClose={closeModal}
            title={editingDefinition ? 'Edit custom property' : 'New custom property'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitCustomPropertyForm}
                        loading={isCustomPropertyFormSubmitting}
                        disabledReason={submitDisabledReason}
                    >
                        {editingDefinition ? 'Save' : 'Create'}
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={customPropertyDefinitionsLogic}
                formKey="customPropertyForm"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="e.g. ARR" autoFocus />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea placeholder="Optional description" minRows={2} />
                </LemonField>
                <LemonField name="displayType" label="Type">
                    <LemonSelect options={DISPLAY_TYPE_OPTIONS} fullWidth />
                </LemonField>
                {showBigNumberSwitch && (
                    <LemonField name="isBigNumber">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value}
                                onChange={onChange}
                                label="Abbreviate large numbers (e.g. 10,000 → 10K)"
                                bordered
                            />
                        )}
                    </LemonField>
                )}
                <LemonField name="sourceMode" label="Source">
                    {({ value, onChange }) => (
                        <LemonSegmentedButton
                            value={value}
                            onChange={onChange}
                            options={SOURCE_MODE_OPTIONS}
                            fullWidth
                        />
                    )}
                </LemonField>
                {hasExistingSource && sourceMode !== 'data_warehouse' && (
                    <LemonBanner type="warning">
                        Saving will remove this property's data warehouse sync. Values already synced will stay, but
                        they'll stop updating automatically.
                    </LemonBanner>
                )}
                {sourceMode === 'data_warehouse' &&
                    (noViews ? (
                        <LemonBanner type="info">
                            No materialized views found. Create and materialize a view in the data warehouse first, then
                            it can feed this property.
                        </LemonBanner>
                    ) : (
                        <>
                            <LemonField
                                name="savedQuery"
                                label="View"
                                help="Values are pulled from this materialized view on each materialization, matched to accounts by external ID."
                            >
                                {({ value, onChange }) => (
                                    <LemonSearchableSelect
                                        value={value}
                                        onChange={(newValue) => {
                                            onChange(newValue)
                                            // Columns are view-specific, so a view change invalidates the picks.
                                            setCustomPropertyFormValue('sourceColumn', null)
                                            setCustomPropertyFormValue('keyColumn', null)
                                        }}
                                        options={materializedViews.map((view) => ({
                                            value: view.id,
                                            label: view.name,
                                        }))}
                                        loading={savedQueriesLoading}
                                        disabledReason={
                                            hasExistingSource ? 'The view is fixed once a sync is created' : undefined
                                        }
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
                                        options={selectedSourceColumns.map((column) => ({
                                            value: column,
                                            label: column,
                                        }))}
                                        loading={savedQueriesLoading}
                                        disabledReason={
                                            !customPropertyForm.savedQuery ? 'Select a view first' : undefined
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
                                        options={selectedSourceColumns.map((column) => ({
                                            value: column,
                                            label: column,
                                        }))}
                                        loading={savedQueriesLoading}
                                        disabledReason={
                                            !customPropertyForm.savedQuery ? 'Select a view first' : undefined
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
                        </>
                    ))}
            </Form>
        </LemonModal>
    )
}
