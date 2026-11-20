import { Field as KeaField } from 'kea-forms'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    Autocomplete,
    AutocompleteContent,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteList,
    Badge,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    FieldDescription,
    Item,
    ItemContent,
    ItemDescription,
    Input,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import type { ColumnPropertyMapping, WarehouseColumn, WarehouseSourceOption } from './customPropertyDefinitionsLogic'

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
            <Label>{isView ? 'Materialized view' : 'Warehouse table'}</Label>
            {tableName ? (
                <span className="flex items-center gap-2">
                    {sourceUrl ? (
                        <Button
                            variant="link"
                            size="sm"
                            nativeButton={false}
                            render={<LinkPrimitive to={sourceUrl} target="_blank" />}
                        >
                            <code>{tableName}</code>
                        </Button>
                    ) : (
                        <code>{tableName}</code>
                    )}
                    <Badge>{isView ? 'View' : 'Table'}</Badge>
                </span>
            ) : (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    This {isView ? 'view' : 'table'} isn't available. It may have been deleted, or you may not have
                    access to it.
                </Text>
            )}
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Rows from here update matching {entityPlural} on every run. You can't change what a property reads after
                it's created.
            </Text>
        </div>
    )
}

function ReadOnlyGroupType({ label, loading }: { label: string | null; loading: boolean }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Label>Group type</Label>
            {loading ? (
                <Skeleton className="h-4 w-24" />
            ) : label ? (
                <Text size="xs" render={<span className="m-0" />}>
                    {label}
                </Text>
            ) : (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    This group type isn't available. It may have been removed from the project.
                </Text>
            )}
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                You can't change the group type after the property is created.
            </Text>
        </div>
    )
}

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
            <Label>Column mappings</Label>
            {mapped.length ? (
                <div className="flex flex-col gap-1">
                    {mapped.map((mapping) => (
                        <Item key={mapping.column} variant="outline" size="xs">
                            <ItemContent>
                                <span className="flex items-center gap-2">
                                    <code>{mapping.column}</code>
                                    <span className="text-muted-foreground">→</span>
                                    <code>{mapping.property}</code>
                                </span>
                                {mapping.description && <ItemDescription>{mapping.description}</ItemDescription>}
                            </ItemContent>
                        </Item>
                    ))}
                </div>
            ) : (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    This source has no column mappings.
                </Text>
            )}
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Which warehouse column sets which {entityLabel} property. You can't change the mappings after the
                property is created. To change them, delete this property and create a new one.
            </Text>
        </div>
    )
}

function ColumnAutocomplete({
    id,
    value,
    columns,
    placeholder,
    ariaLabel,
    onType,
    onPick,
}: {
    id?: string
    value: string
    columns: WarehouseColumn[]
    placeholder: string
    ariaLabel?: string
    onType: (column: string) => void
    onPick: (column: string) => void
}): JSX.Element {
    const typesByName = new Map(columns.map((column) => [column.name, column.type]))

    return (
        <Autocomplete
            items={columns.map((column) => column.name)}
            value={value}
            onValueChange={(next: string, eventDetails) =>
                eventDetails.reason === 'item-press' ? onPick(next) : onType(next)
            }
        >
            <AutocompleteInput id={id} showSearchIcon={false} placeholder={placeholder} aria-label={ariaLabel} />
            <AutocompleteContent>
                <AutocompleteList>
                    {(name: string) => (
                        <AutocompleteItem key={name} value={name}>
                            <span className="flex items-center gap-2">
                                <span>{name}</span>
                                <Badge>{typesByName.get(name)}</Badge>
                            </span>
                        </AutocompleteItem>
                    )}
                </AutocompleteList>
            </AutocompleteContent>
        </Autocomplete>
    )
}

export interface QuillPersonSourceEditorProps {
    noSources: boolean
    isGroup: boolean
    entityLabel: string
    entityPlural: string
    isEditing: boolean
    hasExistingSource: boolean
    existingBindsAView: boolean
    existingTableName: string | null
    existingSourceUrl: string | null
    groupTypeOptions: { value: number; label: string }[]
    selectedGroupTypeLabel: string | null
    groupTypesLoading: boolean
    warehouseSourceOptions: WarehouseSourceOption[]
    warehouseSourcesLoading: boolean
    selectedTableColumns: WarehouseColumn[]
    selectedTableColumnsLoading: boolean
    mappings: ColumnPropertyMapping[]
    columnMappingWarnings: (string | null)[]
    warningCount: number
    keyColumnLabelText: string
    mappableColumnCount: number
    mapAllDisabledReason: string | undefined
    onWarehouseSourceChange: (newValue: string | null, onChange: (value: string | null) => void) => void
    onWarehouseSourceSearch: (search: string) => void
    onMappingColumnChange: (index: number, column: string) => void
    /** Sets a typed column without seeding the property, which only a picked column does. */
    onMappingColumnType: (index: number, column: string) => void
    onMappingPropertyChange: (index: number, property: string) => void
    onRemoveMapping: (index: number) => void
    onAddMapping: () => void
    onMapAllColumns: () => void
}

export function QuillPersonSourceEditor({
    noSources,
    isGroup,
    entityLabel,
    entityPlural,
    isEditing,
    hasExistingSource,
    existingBindsAView,
    existingTableName,
    existingSourceUrl,
    groupTypeOptions,
    selectedGroupTypeLabel,
    groupTypesLoading,
    warehouseSourceOptions,
    warehouseSourcesLoading,
    selectedTableColumns,
    selectedTableColumnsLoading,
    mappings,
    columnMappingWarnings,
    warningCount,
    keyColumnLabelText,
    mappableColumnCount,
    mapAllDisabledReason,
    onWarehouseSourceChange,
    onWarehouseSourceSearch,
    onMappingColumnChange,
    onMappingColumnType,
    onMappingPropertyChange,
    onRemoveMapping,
    onAddMapping,
    onMapAllColumns,
}: QuillPersonSourceEditorProps): JSX.Element {
    const sourceOptionsByValue = new Map(warehouseSourceOptions.map((option) => [option.value, option]))

    // Only block on missing sources while creating a property. An existing source still needs its key
    // column and enabled switch editable even if what it reads was later deleted or filtered out.
    if (noSources && !hasExistingSource) {
        return (
            <Item tone="info" size="sm">
                <ItemContent>
                    <ItemDescription>
                        No data warehouse tables or materialized views found. Connect and sync a source, or materialize
                        a view, then it can feed {entityLabel} properties.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <>
            {isGroup &&
                (isEditing ? (
                    <ReadOnlyGroupType label={selectedGroupTypeLabel} loading={groupTypesLoading} />
                ) : (
                    <QuillSettingFormField name="groupTypeIndex" label="Group type">
                        {({ id, value, onChange }) => (
                            <>
                                <Select items={groupTypeOptions} value={value ?? null} onValueChange={onChange}>
                                    <SelectTrigger id={id} className="w-full">
                                        <SelectValue placeholder="Select a group type" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {groupTypeOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                <FieldDescription>Which group type this property attaches to.</FieldDescription>
                            </>
                        )}
                    </QuillSettingFormField>
                ))}
            {hasExistingSource ? (
                <ReadOnlyWarehouseSource
                    entityPlural={entityPlural}
                    isView={existingBindsAView}
                    tableName={existingTableName}
                    sourceUrl={existingSourceUrl}
                />
            ) : (
                <QuillSettingFormField name="warehouseSource" label="Warehouse source">
                    {({ id, value, onChange }) => (
                        <>
                            <Combobox
                                items={warehouseSourceOptions.map((option) => option.value)}
                                value={value ?? null}
                                onValueChange={(next: string | null) => onWarehouseSourceChange(next, onChange)}
                                onInputValueChange={(search: string, eventDetails) => {
                                    // Table search runs on the backend so the whole synced catalog is reachable,
                                    // not just the first page loaded into the picker. Views are all loaded
                                    // already, so the picker filters those itself.
                                    if (eventDetails.reason === 'input-change') {
                                        onWarehouseSourceSearch(search)
                                    }
                                }}
                                itemToStringLabel={(source: string) =>
                                    sourceOptionsByValue.get(source)?.label ?? source
                                }
                            >
                                <ComboboxInput id={id} placeholder="Select a table or view" showClear />
                                <ComboboxContent>
                                    <ComboboxEmpty>
                                        {warehouseSourcesLoading
                                            ? 'Loading tables and views…'
                                            : 'No matching tables or views'}
                                    </ComboboxEmpty>
                                    <ComboboxList>
                                        {(source: string) => {
                                            const option = sourceOptionsByValue.get(source)
                                            return (
                                                <ComboboxItem key={source} value={source}>
                                                    <span className="flex items-center gap-2">
                                                        <span>{option?.label ?? source}</span>
                                                        <Badge>{option?.kind === 'view' ? 'View' : 'Table'}</Badge>
                                                    </span>
                                                </ComboboxItem>
                                            )
                                        }}
                                    </ComboboxList>
                                </ComboboxContent>
                            </Combobox>
                            <FieldDescription>
                                Rows from this table or view are written onto matching {entityLabel}s. Type to search
                                synced tables and materialized views.
                            </FieldDescription>
                        </>
                    )}
                </QuillSettingFormField>
            )}
            <QuillSettingFormField name="keyColumn" label={isGroup ? 'Group key column' : 'Distinct ID column'}>
                {({ id, value, onChange }) => (
                    <>
                        <ColumnAutocomplete
                            id={id}
                            value={value ?? ''}
                            columns={selectedTableColumns}
                            placeholder={selectedTableColumnsLoading ? 'Loading columns…' : 'e.g. distinct_id'}
                            onType={(column) => onChange(column || null)}
                            onPick={(column) => onChange(column || null)}
                        />
                        <FieldDescription>
                            The column holding each row's {isGroup ? 'group key' : 'distinct ID'}. It's used to match
                            the {entityLabel} to update.
                        </FieldDescription>
                    </>
                )}
            </QuillSettingFormField>
            {hasExistingSource ? (
                <ReadOnlyColumnMappings entityLabel={entityLabel} mappings={mappings} />
            ) : (
                <div className="flex flex-col gap-2">
                    <Label>Column mappings</Label>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Map each warehouse column to the {entityLabel} property name it should set.
                    </Text>
                    {mappings.map((mapping, index) => (
                        <div key={index} className="flex flex-col gap-1">
                            <div className="flex items-center gap-2">
                                <div className="min-w-0 flex-1">
                                    <ColumnAutocomplete
                                        value={mapping.column}
                                        columns={selectedTableColumns}
                                        placeholder="Warehouse column"
                                        ariaLabel="Warehouse column"
                                        onType={(column) => onMappingColumnType(index, column)}
                                        onPick={(column) => onMappingColumnChange(index, column)}
                                    />
                                </div>
                                <span className="text-muted-foreground">→</span>
                                <div className="min-w-0 flex-1">
                                    <Input
                                        value={mapping.property}
                                        onChange={(event) => onMappingPropertyChange(index, event.target.value)}
                                        placeholder={`${isGroup ? 'Group' : 'Person'} property`}
                                        aria-label={`${isGroup ? 'Group' : 'Person'} property`}
                                    />
                                </div>
                                <Button
                                    size="icon"
                                    aria-label="Remove mapping"
                                    tooltip="Remove mapping"
                                    disabledReason={
                                        mappings.length === 1 ? 'At least one mapping is required' : undefined
                                    }
                                    onClick={() => onRemoveMapping(index)}
                                >
                                    <IconTrash />
                                </Button>
                            </div>
                            {columnMappingWarnings[index] && (
                                <Text size="xs" className="m-0 text-warning-foreground" render={<p />}>
                                    {columnMappingWarnings[index]}
                                </Text>
                            )}
                        </div>
                    ))}
                    {warningCount > 0 && (
                        <Text size="xs" className="m-0 text-warning-foreground" render={<p />}>
                            {warningCount === 1
                                ? '1 mapping needs a look before you save.'
                                : `${warningCount} mappings need a look before you save.`}
                        </Text>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <Button variant="outline" onClick={onAddMapping}>
                            <IconPlus />
                            Add mapping
                        </Button>
                        <Button variant="outline" onClick={onMapAllColumns} disabledReason={mapAllDisabledReason}>
                            {mappableColumnCount > 0 ? `Map ${mappableColumnCount} more columns` : 'Map all columns'}
                        </Button>
                    </div>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Mapping every column keeps the warehouse column names. The {keyColumnLabelText} is left out,
                        because its values identify the {entityLabel} rather than describing it. Nothing is saved until
                        you create the property, so you can edit or remove any row first.
                    </Text>
                </div>
            )}
            <KeaField name="isEnabled" noStyle>
                {({ value, onChange }) => (
                    <div className="flex flex-col gap-1">
                        <QuillSettingSwitch
                            label="Sync enabled"
                            help={`Keeps the mapped ${entityLabel} properties updated on every run of what this property reads. Disabling stops updates. It doesn't remove values already written.`}
                            checked={value}
                            onCheckedChange={onChange}
                        />
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            When on, every run of the table or view updates the mapped {entityLabel} properties, and
                            each run writes the rows that changed. Turn it off to stop updating those properties without
                            deleting the mapping. Values already written stay.
                        </Text>
                    </div>
                )}
            </KeaField>
        </>
    )
}
