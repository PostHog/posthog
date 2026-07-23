import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconInfo, IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
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
    Tooltip,
} from '@posthog/lemon-ui'

import type { DataColorToken } from 'lib/colors'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'

import type { CustomPropertyOptionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    CustomPropertySourceMode,
    CustomPropertyTargetType,
    customPropertyDefinitionsLogic,
} from './customPropertyDefinitionsLogic'
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

const TARGET_TYPE_OPTIONS: { value: CustomPropertyTargetType; label: string }[] = [
    { value: 'account', label: 'Account' },
    { value: 'person', label: 'Person' },
    { value: 'group', label: 'Group' },
]

// Warehouse-profile editor (person or group target): pick a synced warehouse table, the key column
// (a person's distinct_id or a group's key), and the column → property mappings. For group targets it
// also picks which group type. The binding + mappings are create-only on the backend, so they're
// read-only once a source exists (only the key column + enabled switch stay editable).
function PersonSourceEditor(): JSX.Element {
    const {
        customPropertyForm,
        warehouseTables,
        warehouseTablesLoading,
        editingDefinition,
        columnMappingWarnings,
        selectedTableColumns,
        selectedTableColumnsLoading,
    } = useValues(customPropertyDefinitionsLogic)
    const { setCustomPropertyFormValue, loadSelectedTableColumns, loadWarehouseTables } =
        useActions(customPropertyDefinitionsLogic)
    const { groupTypes } = useValues(groupsModel)

    const isGroup = customPropertyForm.targetType === 'group'
    const entityLabel = isGroup ? 'group' : 'person'
    const hasExistingSource = !!editingDefinition?.source
    const noTables = !warehouseTablesLoading && warehouseTables.length === 0
    const mappings = customPropertyForm.columnMappings
    const setMappings = (next: typeof mappings): void => setCustomPropertyFormValue('columnMappings', next)
    const columnByName = new Map(selectedTableColumns.map((column) => [column.name, column]))
    // Each column option renders its name with a tag for its warehouse type, so a picker shows what
    // kind of value it holds without leaving the modal.
    const columnOptions = selectedTableColumns.map((column) => ({
        key: column.name,
        label: column.name,
        labelComponent: (
            <span className="flex items-center gap-2">
                <span>{column.name}</span>
                <LemonTag type="muted">{column.type}</LemonTag>
            </span>
        ),
    }))
    const groupTypeOptions = Array.from(groupTypes.values()).map((groupType) => ({
        value: groupType.group_type_index,
        label: groupType.name_singular || groupType.group_type,
    }))

    // Only block on missing tables while creating a source — an existing source still needs its
    // key column and enabled switch editable even if its table was later deleted or filtered out.
    if (noTables && !hasExistingSource) {
        return (
            <LemonBanner type="info">
                No synced data warehouse tables found. Connect and sync a source (e.g. your users table) first, then it
                can feed person properties.
            </LemonBanner>
        )
    }

    return (
        <>
            {isGroup && !hasExistingSource && (
                <LemonField name="groupTypeIndex" label="Group type" help="Which group type this property attaches to.">
                    {({ value, onChange }) => (
                        <LemonSelect
                            value={value}
                            onChange={onChange}
                            options={groupTypeOptions}
                            placeholder="Select a group type"
                            fullWidth
                        />
                    )}
                </LemonField>
            )}
            {hasExistingSource ? (
                <LemonBanner type="info">
                    The warehouse table and column mappings are fixed once a source is created. To change them, delete
                    this property and create a new one. You can still update the {isGroup ? 'group key' : 'distinct ID'}{' '}
                    column and toggle syncing.
                </LemonBanner>
            ) : (
                <LemonField
                    name="warehouseTable"
                    label="Warehouse table"
                    help={`Rows from this synced table are upserted onto matching ${entityLabel}s. Type to search all synced tables.`}
                >
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="single"
                            value={value ? [value] : []}
                            onChange={(newValues) => {
                                const newValue = newValues[0] ?? null
                                onChange(newValue)
                                // Columns are table-specific, so a table change invalidates the picks and
                                // loads the new table's columns for the pickers below.
                                setCustomPropertyFormValue('keyColumn', null)
                                setMappings(mappings.map((mapping) => ({ ...mapping, column: '', description: '' })))
                                if (newValue) {
                                    loadSelectedTableColumns({ tableId: newValue })
                                }
                            }}
                            // Search runs on the backend so the whole synced catalog is reachable, not just
                            // the first page loaded into the picker.
                            onInputChange={(search) => loadWarehouseTables({ search })}
                            options={warehouseTables.map((table) => ({
                                key: table.id,
                                label: table.hogql_name || table.name,
                            }))}
                            loading={warehouseTablesLoading}
                            placeholder="Select a warehouse table"
                        />
                    )}
                </LemonField>
            )}
            <LemonField
                name="keyColumn"
                label={isGroup ? 'Group key column' : 'Distinct ID column'}
                help={`The column holding each row's ${
                    isGroup ? 'group key' : 'distinct ID'
                } — used to match the ${entityLabel} to update.`}
            >
                {({ value, onChange }) => (
                    <LemonInputSelect
                        mode="single"
                        allowCustomValues
                        value={value ? [value] : []}
                        onChange={(newValues) => onChange(newValues[0] ?? null)}
                        options={columnOptions}
                        loading={selectedTableColumnsLoading}
                        placeholder="e.g. distinct_id"
                    />
                )}
            </LemonField>
            {!hasExistingSource && (
                <div className="flex flex-col gap-2">
                    <LemonLabel>Column mappings</LemonLabel>
                    <span className="text-secondary text-xs">
                        Map each warehouse column to the {entityLabel} property name it should set.
                    </span>
                    {mappings.map((mapping, index) => (
                        <div key={index} className="flex flex-col gap-1 border rounded p-2">
                            <div className="flex items-center gap-2">
                                <div className="flex-1">
                                    <LemonInputSelect
                                        mode="single"
                                        allowCustomValues
                                        value={mapping.column ? [mapping.column] : []}
                                        onChange={(newValues) => {
                                            const column = newValues[0] ?? ''
                                            const columnMeta = columnByName.get(column)
                                            setMappings(
                                                mappings.map((m, i) =>
                                                    i === index
                                                        ? {
                                                              ...m,
                                                              column,
                                                              // Seed the property name and description from the
                                                              // column when they're still empty, so a mapping is
                                                              // one click when the warehouse names are good.
                                                              property: m.property.trim() ? m.property : column,
                                                              description: m.description.trim()
                                                                  ? m.description
                                                                  : (columnMeta?.description ?? ''),
                                                          }
                                                        : m
                                                )
                                            )
                                        }}
                                        options={columnOptions}
                                        loading={selectedTableColumnsLoading}
                                        placeholder="Warehouse column"
                                    />
                                </div>
                                <span className="text-secondary">→</span>
                                <div className="flex-1">
                                    <LemonInput
                                        value={mapping.property}
                                        onChange={(property) =>
                                            setMappings(mappings.map((m, i) => (i === index ? { ...m, property } : m)))
                                        }
                                        placeholder={`${isGroup ? 'Group' : 'Person'} property`}
                                        fullWidth
                                    />
                                </div>
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    tooltip="Remove mapping"
                                    disabledReason={
                                        mappings.length === 1 ? 'At least one mapping is required' : undefined
                                    }
                                    onClick={() => setMappings(mappings.filter((_, i) => i !== index))}
                                />
                            </div>
                            <LemonInput
                                value={mapping.description}
                                onChange={(description) =>
                                    setMappings(mappings.map((m, i) => (i === index ? { ...m, description } : m)))
                                }
                                placeholder="Description (optional)"
                                size="small"
                                fullWidth
                            />
                            {columnMappingWarnings[index] && (
                                <span className="text-warning text-xs">{columnMappingWarnings[index]}</span>
                            )}
                        </div>
                    ))}
                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        onClick={() => setMappings([...mappings, { column: '', property: '', description: '' }])}
                    >
                        Add mapping
                    </LemonButton>
                </div>
            )}
            <LemonField
                name="isEnabled"
                help={`When on, this table's syncs update the mapped ${entityLabel} properties, and each sync backfills changed rows. Turn it off to stop updating those properties without deleting the mapping; values already synced stay.`}
            >
                {({ value, onChange }) => (
                    <LemonSwitch
                        checked={value}
                        onChange={onChange}
                        label={
                            <span className="flex items-center gap-1">
                                Sync enabled
                                <Tooltip
                                    title={`Keeps the mapped ${entityLabel} properties updated from this warehouse table on every sync. Disabling stops updates; it doesn't remove values already written.`}
                                >
                                    <IconInfo className="text-secondary" />
                                </Tooltip>
                            </span>
                        }
                        bordered
                    />
                )}
            </LemonField>
        </>
    )
}

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
        targetTypeLocked,
    } = useValues(customPropertyDefinitionsLogic)
    const {
        closeModal,
        submitCustomPropertyForm,
        setCustomPropertyFormValue,
        loadDefinitions,
        createWorkflowForProperty,
    } = useActions(customPropertyDefinitionsLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const showBigNumberSwitch = isNumericDisplayType(customPropertyForm.displayType)
    const { sourceMode, targetType } = customPropertyForm
    const isProfileTarget = targetType === 'person' || targetType === 'group'
    // Person/group-target properties are gated behind the rollout flag; an existing profile property
    // stays editable so a rollback doesn't strand its configuration.
    const profileTargetAvailable = !!featureFlags[FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES] || isProfileTarget
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

    // A new person/group source needs at least one complete column → property pair. The mapping rows
    // aren't LemonFields, so this gates the submit button rather than showing a per-field error.
    const missingPersonMapping =
        isProfileTarget &&
        !hasExistingSource &&
        !customPropertyForm.columnMappings.some((mapping) => mapping.column.trim() && mapping.property.trim())

    const submitDisabledReason =
        // The select-options gate is account-only — the Type field is hidden for person, where a
        // leftover 'select' from switching targets would otherwise wedge the submit button.
        targetType === 'account' &&
        customPropertyForm.displayType === 'select' &&
        customPropertyForm.options.length === 0
            ? 'Add at least one option'
            : missingPersonMapping
              ? 'Map at least one column to a property'
              : targetType === 'account' && sourceMode === 'data_warehouse' && noViews
                ? 'No materialized views are available'
                : targetType === 'account' && sourceMode === 'workflow' && editingReferences.length === 0
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
                {profileTargetAvailable && !targetTypeLocked && (
                    <LemonField
                        name="targetType"
                        label="Attach to"
                        help="Account properties describe a customer; person properties attach to individual people and are usable in feature flags, cohorts and insights."
                    >
                        {({ value, onChange }) => (
                            <LemonSegmentedButton
                                value={value}
                                onChange={onChange}
                                options={TARGET_TYPE_OPTIONS.map((option) => ({
                                    ...option,
                                    disabledReason: editingDefinition
                                        ? "A property's target can't change after it's created"
                                        : undefined,
                                }))}
                                fullWidth
                            />
                        )}
                    </LemonField>
                )}
                {/* Type, big-number and options only drive how an account property is rendered — a
                    person property is a raw $set value, so these are account-only. */}
                {targetType === 'account' && (
                    <>
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
                    </>
                )}
                {isProfileTarget && <PersonSourceEditor />}
                {targetType === 'account' && (
                    <>
                        <LemonField name="sourceMode" label="Source">
                            {({ value, onChange }) => (
                                <LemonSegmentedButton
                                    value={value}
                                    onChange={onChange}
                                    options={sourceModeOptions}
                                    fullWidth
                                />
                            )}
                        </LemonField>
                        {hasExistingSource && sourceMode !== 'data_warehouse' && (
                            <LemonBanner type="warning">
                                Saving will remove this property's data warehouse sync. Values already synced will stay,
                                but they'll stop updating automatically.
                            </LemonBanner>
                        )}
                        {sourceMode === 'data_warehouse' &&
                            (noViews ? (
                                <LemonBanner type="info">
                                    No materialized views found. Create and materialize a view in the data warehouse
                                    first, then it can feed this property.
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
                                                    hasExistingSource
                                                        ? 'The view is fixed once a sync is created'
                                                        : undefined
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
                                            <LemonSwitch
                                                checked={value}
                                                onChange={onChange}
                                                label="Sync enabled"
                                                bordered
                                            />
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
                                            No workflows update this property yet. Create one with an "Update account
                                            property" action that sets this property — the editor opens in a new tab.
                                            Once you save the workflow there, refresh this list.
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
                    </>
                )}
            </Form>
        </LemonModal>
    )
}
