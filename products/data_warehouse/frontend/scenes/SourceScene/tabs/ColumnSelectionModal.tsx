import { useEffect, useMemo, useState } from 'react'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, Tooltip } from '@posthog/lemon-ui'

import { ExternalDataSourceSchema } from '~/types'

// Unifies the existing-source schema and the wizard's pre-creation sync schema so
// both can drive the picker without coupling it to either concrete type.
export interface ColumnSelectionTarget {
    id: string
    name?: string
    enabled_columns?: string[] | null
    masked_columns?: string[] | null
    primary_key_columns?: string[] | null
    incremental_field?: string | null
    available_columns?: { name: string; data_type?: string; is_nullable?: boolean }[]
}

interface ColumnSelectionPickerProps {
    schema: ColumnSelectionTarget | null
    onSave?: (enabledColumns: string[] | null) => void
    onCancel?: () => void
    hideActions?: boolean
    /** Fires on every edit, so a parent can drive saving with its own button. */
    onChange?: (enabledColumns: string[] | null) => void
    /** Show a mask toggle on each column. */
    enableMasking?: boolean
    onMaskedChange?: (maskedColumns: string[]) => void
}

interface ColumnSelectionModalProps {
    isOpen: boolean
    schema: ExternalDataSourceSchema | null
    onClose: () => void
    onSave: (enabledColumns: string[] | null) => void
}

interface UseColumnSelectionResult {
    selected: Set<string> | null
    filter: string
    setFilter: (value: string) => void
    setSyncAll: () => void
    toggleColumn: (name: string, checked: boolean) => void
    isAlwaysRetained: (name: string) => boolean
    isChecked: (name: string) => boolean
    isMasked: (name: string) => boolean
    isMaskable: (name: string) => boolean
    toggleMask: (name: string) => void
    persistedSelection: () => string[] | null
    available: { name: string; data_type?: string; is_nullable?: boolean }[]
    primaryKeys: Set<string>
    incrementalField: string | null | undefined
    filteredColumns: { name: string; data_type?: string; is_nullable?: boolean }[]
}

function useColumnSelection(
    schema: ColumnSelectionTarget | null,
    onChange?: (enabledColumns: string[] | null) => void,
    onMaskedChange?: (maskedColumns: string[]) => void
): UseColumnSelectionResult {
    const available = schema?.available_columns ?? []
    const primaryKeys = useMemo(() => new Set(schema?.primary_key_columns ?? []), [schema?.primary_key_columns])
    const incrementalField = schema?.incremental_field

    const [selected, setSelected] = useState<Set<string> | null>(null)
    const [masked, setMasked] = useState<Set<string>>(new Set())
    const [filter, setFilter] = useState('')

    useEffect(() => {
        const current = schema?.enabled_columns
        setSelected(Array.isArray(current) ? new Set(current) : null)
        setMasked(new Set(schema?.masked_columns ?? []))
        setFilter('')
        // Stable serialized key: the array ref changes on every poll even with identical contents,
        // which would otherwise wipe out in-progress edits.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [schema?.id, schema?.enabled_columns?.join('\0') ?? null, schema?.masked_columns?.join('\0') ?? null])

    const isAlwaysRetained = (name: string): boolean => primaryKeys.has(name) || name === incrementalField

    const isChecked = (name: string): boolean => {
        if (isAlwaysRetained(name)) {
            return true
        }
        if (selected === null) {
            return true
        }
        return selected.has(name)
    }

    // PKs + incremental are always synced — including them explicitly keeps the persisted
    // list legible (e.g. ["id"] reads as "PK only" rather than the ambiguous []).
    const computePersisted = (sel: Set<string> | null): string[] | null => {
        if (sel === null) {
            return null
        }
        const result = new Set(sel)
        primaryKeys.forEach((pk) => result.add(pk))
        if (incrementalField) {
            result.add(incrementalField)
        }
        return Array.from(result)
    }

    const commit = (next: Set<string> | null): void => {
        setSelected(next)
        onChange?.(computePersisted(next))
    }

    const toggleColumn = (name: string, checked: boolean): void => {
        if (isAlwaysRetained(name)) {
            return
        }
        const baseline = selected ?? new Set(available.map((c) => c.name))
        const next = new Set(baseline)
        if (checked) {
            next.add(name)
        } else {
            next.delete(name)
        }
        commit(next)
    }

    const commitMasked = (name: string, shouldMask: boolean): void => {
        const next = new Set(masked)
        if (shouldMask) {
            next.add(name)
        } else {
            next.delete(name)
        }
        setMasked(next)
        onMaskedChange?.(Array.from(next))
    }

    const isMasked = (name: string): boolean => masked.has(name)

    // A hashed primary key breaks merges and a hashed incremental field cannot order rows.
    const isMaskable = (name: string): boolean => isChecked(name) && !isAlwaysRetained(name)

    // A column masked before it became a key can still be unmasked, so the rejected save can be fixed.
    const toggleMask = (name: string): void => {
        if (masked.has(name)) {
            commitMasked(name, false)
        } else if (isMaskable(name)) {
            commitMasked(name, true)
        }
    }

    const setSyncAll = (): void => commit(null)

    const filteredColumns = useMemo(() => {
        const term = filter.trim().toLowerCase()
        if (!term) {
            return available
        }
        return available.filter((column) => column.name.toLowerCase().includes(term))
    }, [available, filter])

    const persistedSelection = (): string[] | null => computePersisted(selected)

    return {
        selected,
        filter,
        setFilter,
        setSyncAll,
        toggleColumn,
        isAlwaysRetained,
        isChecked,
        isMasked,
        isMaskable,
        toggleMask,
        persistedSelection,
        available,
        primaryKeys,
        incrementalField,
        filteredColumns,
    }
}

export function ColumnSelectionPicker({
    schema,
    onSave,
    onCancel,
    hideActions,
    onChange,
    enableMasking,
    onMaskedChange,
}: ColumnSelectionPickerProps): JSX.Element {
    const {
        filter,
        setFilter,
        setSyncAll,
        toggleColumn,
        isAlwaysRetained,
        isChecked,
        isMasked,
        isMaskable,
        toggleMask,
        persistedSelection,
        available,
        primaryKeys,
        filteredColumns,
    } = useColumnSelection(schema, onChange, onMaskedChange)

    return (
        <div className="flex flex-col gap-2">
            <LemonInput type="search" placeholder="Filter columns" size="small" value={filter} onChange={setFilter} />
            <div className="max-h-96 overflow-y-auto border rounded">
                {available.length === 0 && (
                    <div className="text-center text-muted-alt py-6 text-sm">
                        No columns discovered yet. Run "Pull new schemas" on the source's Schemas tab first.
                    </div>
                )}
                {filteredColumns.map((column) => {
                    const retained = isAlwaysRetained(column.name)
                    const checkbox = (
                        <LemonCheckbox
                            checked={isChecked(column.name)}
                            disabled={retained}
                            onChange={(checked) => toggleColumn(column.name, checked)}
                            label={
                                <div className="flex items-center gap-2">
                                    <code>{column.name}</code>
                                    {column.data_type && (
                                        <span className="text-xs text-muted-alt">{column.data_type}</span>
                                    )}
                                    {retained && (
                                        <span className="text-xs text-muted">
                                            {primaryKeys.has(column.name) ? 'primary key' : 'incremental field'}
                                        </span>
                                    )}
                                </div>
                            }
                        />
                    )
                    return (
                        <div key={column.name} className="flex items-center justify-between gap-2 px-3 py-1">
                            {retained ? (
                                <Tooltip title="Always synced — required for merges or incremental tracking.">
                                    <div>{checkbox}</div>
                                </Tooltip>
                            ) : (
                                checkbox
                            )}
                            {enableMasking &&
                                (isMasked(column.name) ? (
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        icon={<IconLock />}
                                        onClick={() => toggleMask(column.name)}
                                        tooltip="This column syncs as a one-way hash. Click to unmask it and sync its real values again."
                                        data-attr="schema-column-unmask"
                                    >
                                        Masked
                                    </LemonButton>
                                ) : (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() => toggleMask(column.name)}
                                        tooltip="Replace this column's values with a one-way hash when syncing. Use it for passwords and personal data. A masked column no longer matches the same values in tables where it isn't masked."
                                        disabledReason={
                                            isMaskable(column.name)
                                                ? undefined
                                                : retained
                                                  ? "Primary key and incremental columns can't be masked"
                                                  : 'Only synced columns can be masked'
                                        }
                                        data-attr="schema-column-mask"
                                    >
                                        Mask
                                    </LemonButton>
                                ))}
                        </div>
                    )
                })}
                {filteredColumns.length === 0 && available.length > 0 && (
                    <div className="text-center text-muted-alt py-6 text-sm">No columns match.</div>
                )}
            </div>
            {!hideActions && (
                <div className="flex items-center justify-between gap-2 mt-2">
                    <LemonButton type="tertiary" onClick={setSyncAll}>
                        Reset to sync all columns
                    </LemonButton>
                    <div className="flex gap-2">
                        {onCancel && (
                            <LemonButton type="secondary" onClick={onCancel}>
                                Cancel
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            onClick={() => onSave?.(persistedSelection())}
                            disabledReason={available.length === 0 ? 'No columns discovered' : undefined}
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

export function ColumnSelectionModal({ isOpen, schema, onClose, onSave }: ColumnSelectionModalProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`Select columns to sync — ${schema?.name ?? ''}`}
            description="Primary-key and incremental columns are always synced and cannot be unchecked."
        >
            <div className="min-w-[420px]">
                <ColumnSelectionPicker schema={schema} onSave={onSave} onCancel={onClose} />
            </div>
        </LemonModal>
    )
}
