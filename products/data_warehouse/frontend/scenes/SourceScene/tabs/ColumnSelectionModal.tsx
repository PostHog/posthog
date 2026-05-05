import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal, Tooltip } from '@posthog/lemon-ui'

import { ExternalDataSourceSchema } from '~/types'

/**
 * Minimal shape needed to render the column picker. Both `ExternalDataSourceSchema` (existing
 * source) and `ExternalDataSourceSyncSchema` (wizard pre-creation) satisfy this — the picker
 * only needs identity, the column inventory, and the always-retained columns.
 */
export interface ColumnSelectionTarget {
    /** Stable identity used to reset internal state when the user switches between rows. */
    id: string
    name?: string
    synced_columns?: string[] | null
    primary_key_columns?: string[] | null
    incremental_field?: string | null
    available_columns?: { name: string; data_type?: string; is_nullable?: boolean }[]
}

interface ColumnSelectionPickerProps {
    schema: ColumnSelectionTarget | null
    /** When provided, "Save" is enabled and clicking it calls this with the user's selection. */
    onSave: (syncedColumns: string[] | null) => void
    /** Optional secondary button shown next to "Save". */
    onCancel?: () => void
    /** Hide the action buttons — useful when the embedding scene supplies its own save controls. */
    hideActions?: boolean
}

interface ColumnSelectionModalProps {
    isOpen: boolean
    schema: ExternalDataSourceSchema | null
    onClose: () => void
    onSave: (syncedColumns: string[] | null) => void
}

interface UseColumnSelectionResult {
    selected: Set<string> | null
    filter: string
    setFilter: (value: string) => void
    setSyncAll: () => void
    toggleColumn: (name: string, checked: boolean) => void
    isAlwaysRetained: (name: string) => boolean
    isChecked: (name: string) => boolean
    persistedSelection: () => string[] | null
    available: { name: string; data_type?: string; is_nullable?: boolean }[]
    primaryKeys: Set<string>
    incrementalField: string | null | undefined
    filteredColumns: { name: string; data_type?: string; is_nullable?: boolean }[]
}

function useColumnSelection(schema: ColumnSelectionTarget | null): UseColumnSelectionResult {
    const available = schema?.available_columns ?? []
    const primaryKeys = useMemo(() => new Set(schema?.primary_key_columns ?? []), [schema?.primary_key_columns])
    const incrementalField = schema?.incremental_field

    const [selected, setSelected] = useState<Set<string> | null>(null)
    const [filter, setFilter] = useState('')

    useEffect(() => {
        const currentSynced = schema?.synced_columns
        if (Array.isArray(currentSynced) && currentSynced.length > 0) {
            setSelected(new Set(currentSynced))
        } else {
            setSelected(null)
        }
        setFilter('')
    }, [schema?.id, schema?.synced_columns])

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

    const toggleColumn = (name: string, checked: boolean): void => {
        if (isAlwaysRetained(name)) {
            return
        }
        setSelected((current) => {
            const baseline = current ?? new Set(available.map((c) => c.name))
            const next = new Set(baseline)
            if (checked) {
                next.add(name)
            } else {
                next.delete(name)
            }
            return next
        })
    }

    const setSyncAll = (): void => setSelected(null)

    const filteredColumns = useMemo(() => {
        const term = filter.trim().toLowerCase()
        if (!term) {
            return available
        }
        return available.filter((column) => column.name.toLowerCase().includes(term))
    }, [available, filter])

    const persistedSelection = (): string[] | null => {
        if (selected === null) {
            return null
        }
        const persisted = Array.from(selected).filter((name) => !isAlwaysRetained(name))
        return persisted.length > 0 ? persisted : null
    }

    return {
        selected,
        filter,
        setFilter,
        setSyncAll,
        toggleColumn,
        isAlwaysRetained,
        isChecked,
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
}: ColumnSelectionPickerProps): JSX.Element {
    const {
        filter,
        setFilter,
        setSyncAll,
        toggleColumn,
        isAlwaysRetained,
        isChecked,
        persistedSelection,
        available,
        primaryKeys,
        filteredColumns,
    } = useColumnSelection(schema)

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
                        <div key={column.name} className="px-3 py-1">
                            {retained ? (
                                <Tooltip title="Always synced — required for merges or incremental tracking.">
                                    <div>{checkbox}</div>
                                </Tooltip>
                            ) : (
                                checkbox
                            )}
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
                            onClick={() => onSave(persistedSelection())}
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
