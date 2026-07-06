import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonColorPicker,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSearchableSelect,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import type { DataColorToken } from 'lib/colors'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { urls } from 'scenes/urls'

import type { CustomPropertyOptionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { CustomPropertySourceMode, customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import {
    DISPLAY_TYPE_OPTIONS,
    NEW_OPTION_ID_PREFIX,
    OPTION_COLOR_TOKENS,
    isNumericDisplayType,
} from './customPropertyTypes'

const SOURCE_MODE_OPTIONS: { value: CustomPropertySourceMode; label: string }[] = [
    { value: 'manual', label: 'Manual' },
    { value: 'data_warehouse', label: 'Data warehouse' },
    { value: 'workflow', label: 'Workflow' },
]

function CustomPropertyOptionsEditor(): JSX.Element {
    const { customPropertyForm } = useValues(customPropertyDefinitionsLogic)
    const { setCustomPropertyFormValue } = useActions(customPropertyDefinitionsLogic)

    const options = customPropertyForm.options
    const setOptions = (next: CustomPropertyOptionApi[]): void => setCustomPropertyFormValue('options', next)

    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Options</LemonLabel>
            {options.map((option, index) => (
                <div key={option.id ?? index} className="flex items-start gap-2">
                    <LemonColorPicker
                        colorTokens={OPTION_COLOR_TOKENS}
                        selectedColorToken={option.color as DataColorToken}
                        onSelectColorToken={(colorToken) =>
                            setOptions(
                                options.map((candidate, candidateIndex) =>
                                    candidateIndex === index
                                        ? { ...candidate, color: colorToken as CustomPropertyOptionApi['color'] }
                                        : candidate
                                )
                            )
                        }
                        hideDropdown
                    />
                    <div className="flex-1">
                        <LemonField name={['options', index, 'label']}>
                            <LemonInput placeholder="Option label" fullWidth />
                        </LemonField>
                    </div>
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        tooltip="Remove option"
                        onClick={() => setOptions(options.filter((_, candidateIndex) => candidateIndex !== index))}
                    />
                </div>
            ))}
            <LemonButton
                type="secondary"
                icon={<IconPlus />}
                onClick={() =>
                    setOptions([
                        ...options,
                        {
                            id: `${NEW_OPTION_ID_PREFIX}${crypto.randomUUID()}`,
                            label: '',
                            color: OPTION_COLOR_TOKENS[
                                options.length % OPTION_COLOR_TOKENS.length
                            ] as CustomPropertyOptionApi['color'],
                        },
                    ])
                }
            >
                Add option
            </LemonButton>
        </div>
    )
}

export function CustomPropertyModal(): JSX.Element {
    const {
        modalVisible,
        editingDefinition,
        customPropertyForm,
        isCustomPropertyFormSubmitting,
        materializedViews,
        selectedSourceColumns,
        savedQueriesLoading,
        definitionsLoading,
        editingReferences,
        newWorkflowUrlLoading,
    } = useValues(customPropertyDefinitionsLogic)
    const {
        closeModal,
        submitCustomPropertyForm,
        setCustomPropertyFormValue,
        loadDefinitions,
        createWorkflowForProperty,
    } = useActions(customPropertyDefinitionsLogic)

    const showBigNumberSwitch = isNumericDisplayType(customPropertyForm.displayType)
    const { sourceMode } = customPropertyForm
    const hasExistingSource = !!editingDefinition?.source
    const noViews = !savedQueriesLoading && materializedViews.length === 0

    // While a workflow references the property it stays workflow-sourced no matter what is picked
    // here, so the other options are locked until it's removed from the workflow(s).
    const lockedToWorkflow = editingReferences.length > 0 && !hasExistingSource
    const sourceModeOptions = SOURCE_MODE_OPTIONS.map((option) =>
        option.value !== 'workflow' && lockedToWorkflow
            ? {
                  ...option,
                  disabledReason:
                      'This property is updated by a workflow. Remove it from the workflow to change the source.',
              }
            : option
    )

    const submitDisabledReason =
        customPropertyForm.displayType === 'select' && customPropertyForm.options.length === 0
            ? 'Add at least one option'
            : sourceMode === 'data_warehouse' && noViews
              ? 'No materialized views are available'
              : sourceMode === 'workflow' && editingReferences.length === 0
                ? 'Create a workflow that updates this property first'
                : undefined

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
                {customPropertyForm.displayType === 'select' && <CustomPropertyOptionsEditor />}
                <LemonField name="sourceMode" label="Source">
                    {({ value, onChange }) => (
                        <LemonSegmentedButton value={value} onChange={onChange} options={sourceModeOptions} fullWidth />
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
                {sourceMode === 'workflow' && (
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center justify-between">
                            <span className="font-semibold">Workflows updating this property</span>
                            <LemonButton
                                size="small"
                                icon={<IconRefresh />}
                                tooltip="Refresh"
                                onClick={loadDefinitions}
                                loading={definitionsLoading}
                            />
                        </div>
                        {editingReferences.length > 0 ? (
                            <div className="flex flex-col gap-1">
                                {editingReferences.map((reference) => (
                                    <div
                                        key={reference.id}
                                        className="flex items-center justify-between gap-2 border rounded p-2"
                                    >
                                        <Link
                                            to={urls.workflow(reference.id, 'workflow')}
                                            target="_blank"
                                            targetBlankIcon
                                        >
                                            {reference.name}
                                        </Link>
                                        <LemonTag>{reference.status}</LemonTag>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className="border rounded p-4 flex flex-col items-center gap-2 text-center">
                                <span className="text-secondary">
                                    No workflows update this property yet. Create one with an "Update account property"
                                    action that sets this property — the editor opens in a new tab. Once you save the
                                    workflow there, refresh this list.
                                </span>
                                <LemonButton
                                    type="primary"
                                    onClick={createWorkflowForProperty}
                                    loading={newWorkflowUrlLoading}
                                >
                                    Create workflow
                                </LemonButton>
                            </div>
                        )}
                    </div>
                )}
            </Form>
        </LemonModal>
    )
}
