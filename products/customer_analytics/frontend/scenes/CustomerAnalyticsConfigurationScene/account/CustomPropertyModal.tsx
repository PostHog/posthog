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
    LemonSkeleton,
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
    ColumnPropertyMapping,
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

// What an existing source reads, shown as text because the binding is create-only. Links to the table
// or view's own page, where its run history and errors are.
function ReadOnlyWarehouseSource({
    entityPlural,
    isView,
    tableName,
    sourceUrl,
}: {
    entityPlural: string
    isView: boolean
    tableName: string | null
    sourceUrl: string | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <LemonLabel>{isView ? 'Materialized view' : 'Warehouse table'}</LemonLabel>
            {tableName ? (
                <span className="flex items-center gap-2">
                    {sourceUrl ? (
                        <Link to={sourceUrl} target="_blank" targetBlankIcon>
                            <code>{tableName}</code>
                        </Link>
                    ) : (
                        <code>{tableName}</code>
                    )}
                    <LemonTag type="muted">{isView ? 'View' : 'Table'}</LemonTag>
                </span>
            ) : (
                <span className="text-secondary">
                    This {isView ? 'view' : 'table'} isn't available. It may have been deleted, or you may not have
                    access to it.
                </span>
            )}
            <span className="text-secondary text-xs">
                Rows from here update matching {entityPlural} on every run. You can't change what a property reads after
                it's created.
            </span>
        </div>
    )
}

// The group type an existing group property attaches to. Create-only on the backend, so it's shown as
// text — but it still has to be shown, since it's part of what the property is.
function ReadOnlyGroupType({ label, loading }: { label: string | null; loading: boolean }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <LemonLabel>Group type</LemonLabel>
            {loading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : label ? (
                <span>{label}</span>
            ) : (
                <span className="text-secondary">
                    This group type isn't available. It may have been removed from the project.
                </span>
            )}
            <span className="text-secondary text-xs">
                You can't change the group type after the property is created.
            </span>
        </div>
    )
}

// An existing source's column mappings. Create-only on the backend, so they're listed rather than
// edited: what a property reads is the thing you open the modal to check.
function ReadOnlyColumnMappings({
    entityLabel,
    mappings,
}: {
    entityLabel: string
    mappings: ColumnPropertyMapping[]
}): JSX.Element {
    const mapped = mappings.filter((mapping) => mapping.column && mapping.property)
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Column mappings</LemonLabel>
            {mapped.length ? (
                <div className="flex flex-col gap-1">
                    {mapped.map((mapping) => (
                        <div key={mapping.column} className="flex flex-col border rounded px-2 py-1">
                            <span className="flex items-center gap-2">
                                <code>{mapping.column}</code>
                                <span className="text-secondary">→</span>
                                <code>{mapping.property}</code>
                            </span>
                            {mapping.description && (
                                <span className="text-secondary text-xs">{mapping.description}</span>
                            )}
                        </div>
                    ))}
                </div>
            ) : (
                <span className="text-secondary">This source has no column mappings.</span>
            )}
            <span className="text-secondary text-xs">
                Which warehouse column sets which {entityLabel} property. You can't change the mappings after the
                property is created. To change them, delete this property and create a new one.
            </span>
        </div>
    )
}

// Warehouse-profile editor (person or group target): pick a synced warehouse table, the key column
// (a person's distinct_id or a group's key), and the column → property mappings. For group targets it
// also picks which group type. The binding + mappings are create-only on the backend, so they're
// read-only once a source exists (only the key column + enabled switch stay editable).
function PersonSourceEditor(): JSX.Element {
    const {
        customPropertyForm,
        warehouseSourceOptions,
        warehouseTablesLoading,
        savedQueriesLoading,
        editingDefinition,
        columnMappingWarnings,
        selectedTableColumns,
        selectedTableColumnsLoading,
        hasWarehouseSourceOptions,
        mappableColumns,
    } = useValues(customPropertyDefinitionsLogic)
    const { setCustomPropertyFormValue, loadSelectedTableColumns, loadWarehouseTables, mapAllColumns } =
        useActions(customPropertyDefinitionsLogic)
    const { groupTypes, groupTypesLoading } = useValues(groupsModel)

    const isGroup = customPropertyForm.targetType === 'group'
    const entityLabel = isGroup ? 'group' : 'person'
    const entityPlural = isGroup ? 'groups' : 'people'
    const existingSource = editingDefinition?.source
    const hasExistingSource = !!existingSource
    // Deliberately not derived from the picker's options — its search narrows that list, and a search
    // with no matches would otherwise collapse the whole editor into the empty-state banner, taking the
    // search box with it. The picker shows its own "no options matching" instead.
    const noSources = hasWarehouseSourceOptions === false
    const existingBindsAView = !!existingSource?.saved_query && !existingSource?.external_data_schema
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
    const keyColumnLabel = isGroup ? 'group key column' : 'distinct ID column'
    // Bulk mapping needs the key column chosen first, since that is what it excludes. Naming the
    // reason in the disabled state keeps a wide table from being mapped with its identifier in it.
    const mapAllDisabledReason = !customPropertyForm.warehouseSource
        ? 'Select a table or view first'
        : selectedTableColumnsLoading
          ? 'Loading columns'
          : !customPropertyForm.keyColumn?.trim()
            ? `Choose the ${keyColumnLabel} first`
            : !mappableColumns.length
              ? 'Every column is mapped already'
              : undefined
    const warningCount = columnMappingWarnings.filter(Boolean).length
    const groupTypeOptions = Array.from(groupTypes.values()).map((groupType) => ({
        value: groupType.group_type_index,
        label: groupType.name_singular || groupType.group_type,
    }))
    const selectedGroupTypeLabel =
        groupTypeOptions.find((option) => option.value === customPropertyForm.groupTypeIndex)?.label ?? null

    // Only block on missing sources while creating a property — an existing source still needs its key
    // column and enabled switch editable even if what it reads was later deleted or filtered out.
    if (noSources && !hasExistingSource) {
        return (
            <LemonBanner type="info">
                No data warehouse tables or materialized views found. Connect and sync a source, or materialize a view,
                then it can feed {entityLabel} properties.
            </LemonBanner>
        )
    }

    return (
        <>
            {/* group_type_index is create-only on the backend, so on edit it's read-only text rather
                than a picker whose value would be dropped. */}
            {isGroup &&
                (editingDefinition ? (
                    <ReadOnlyGroupType label={selectedGroupTypeLabel} loading={groupTypesLoading} />
                ) : (
                    <LemonField
                        name="groupTypeIndex"
                        label="Group type"
                        help="Which group type this property attaches to."
                    >
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
                ))}
            {hasExistingSource ? (
                <ReadOnlyWarehouseSource
                    entityPlural={entityPlural}
                    isView={existingBindsAView}
                    tableName={existingSource?.saved_query_name ?? existingSource?.table_name ?? null}
                    sourceUrl={
                        existingBindsAView && existingSource?.saved_query
                            ? urls.sqlEditor({ view_id: existingSource.saved_query })
                            : existingSource?.external_data_source && existingSource.external_data_schema
                              ? urls.dataWarehouseSourceSchema(
                                    existingSource.external_data_source,
                                    existingSource.external_data_schema
                                )
                              : null
                    }
                />
            ) : (
                <LemonField
                    name="warehouseSource"
                    label="Warehouse source"
                    help={`Rows from this table or view are written onto matching ${entityLabel}s. Type to search synced tables and materialized views.`}
                >
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="single"
                            value={value ? [value] : []}
                            onChange={(newValues) => {
                                const newValue = newValues[0] ?? null
                                onChange(newValue)
                                // Columns belong to one source, so a change invalidates the picks and
                                // loads the new source's columns for the pickers below.
                                setCustomPropertyFormValue('keyColumn', null)
                                setMappings(mappings.map((mapping) => ({ ...mapping, column: '', description: '' })))
                                // Also load on clear (null) so the pickers below drop the previous source's
                                // stale columns; the loader returns an empty list for null.
                                loadSelectedTableColumns({ source: newValue })
                            }}
                            // Table search runs on the backend so the whole synced catalog is reachable,
                            // not just the first page loaded into the picker. Views are all loaded already,
                            // so the picker filters those itself.
                            onInputChange={(search) => loadWarehouseTables({ search })}
                            options={warehouseSourceOptions.map((option) => ({
                                key: option.value,
                                label: option.label,
                                labelComponent: (
                                    <span className="flex items-center gap-2">
                                        <span>{option.label}</span>
                                        <LemonTag type="muted">{option.kind === 'view' ? 'View' : 'Table'}</LemonTag>
                                    </span>
                                ),
                            }))}
                            loading={warehouseTablesLoading || savedQueriesLoading}
                            placeholder="Select a table or view"
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
            {hasExistingSource ? (
                <ReadOnlyColumnMappings entityLabel={entityLabel} mappings={mappings} />
            ) : (
                <div className="flex flex-col gap-2">
                    <LemonLabel>Column mappings</LemonLabel>
                    <span className="text-secondary text-xs">
                        Map each warehouse column to the {entityLabel} property name it should set.
                    </span>
                    {mappings.map((mapping, index) => (
                        <div key={index} className="flex flex-col gap-1">
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
                                                              // one click when the warehouse names are good. The
                                                              // description has no input here — it rides along
                                                              // from the warehouse column's own description.
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
                            {columnMappingWarnings[index] && (
                                <span className="text-warning text-xs">{columnMappingWarnings[index]}</span>
                            )}
                        </div>
                    ))}
                    {warningCount > 0 && (
                        <span className="text-warning text-xs">
                            {warningCount === 1
                                ? '1 mapped property needs a look before you save.'
                                : `${warningCount} mapped properties need a look before you save.`}
                        </span>
                    )}
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            onClick={() => setMappings([...mappings, { column: '', property: '', description: '' }])}
                        >
                            Add mapping
                        </LemonButton>
                        <LemonButton type="secondary" onClick={mapAllColumns} disabledReason={mapAllDisabledReason}>
                            {mappableColumns.length > 0
                                ? `Map ${mappableColumns.length} more columns`
                                : 'Map all columns'}
                        </LemonButton>
                    </div>
                    <span className="text-secondary text-xs">
                        Mapping every column keeps the warehouse column names. The {keyColumnLabel} is left out, because
                        its values identify the {entityLabel} rather than describing it. Nothing is saved until you
                        create the property, so you can edit or remove any row first.
                    </span>
                </div>
            )}
            <LemonField
                name="isEnabled"
                help={`When on, every run of the table or view updates the mapped ${entityLabel} properties, and each run writes the rows that changed. Turn it off to stop updating those properties without deleting the mapping. Values already written stay.`}
            >
                {({ value, onChange }) => (
                    <LemonSwitch
                        checked={value}
                        onChange={onChange}
                        label={
                            <span className="flex items-center gap-1">
                                Sync enabled
                                <Tooltip
                                    title={`Keeps the mapped ${entityLabel} properties updated on every run of what this property reads. Disabling stops updates. It doesn't remove values already written.`}
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
