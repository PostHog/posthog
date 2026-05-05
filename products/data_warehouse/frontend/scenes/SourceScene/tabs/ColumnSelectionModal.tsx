import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal, Tooltip } from '@posthog/lemon-ui'

import { ExternalDataSourceSchema } from '~/types'

interface ColumnSelectionModalProps {
    isOpen: boolean
    schema: ExternalDataSourceSchema | null
    onClose: () => void
    onSave: (syncedColumns: string[] | null) => void
}

export function ColumnSelectionModal({ isOpen, schema, onClose, onSave }: ColumnSelectionModalProps): JSX.Element {
    const available = schema?.available_columns ?? []
    const primaryKeys = useMemo(() => new Set(schema?.primary_key_columns ?? []), [schema?.primary_key_columns])
    const incrementalField = schema?.incremental_field

    // null = "sync all". Selected = explicit subset.
    const [selected, setSelected] = useState<Set<string> | null>(null)
    const [filter, setFilter] = useState('')

    useEffect(() => {
        if (!isOpen) {
            return
        }
        const currentSynced = schema?.synced_columns
        if (Array.isArray(currentSynced) && currentSynced.length > 0) {
            setSelected(new Set(currentSynced))
        } else {
            setSelected(null)
        }
        setFilter('')
    }, [isOpen, schema?.id, schema?.synced_columns])

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
            // Promote `null` (sync all) to an explicit set when the user first deselects something.
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

    const handleSave = (): void => {
        if (selected === null) {
            onSave(null)
        } else {
            // Strip auto-retained columns from the persisted list so re-running discovery never
            // surfaces them as user-selected explicitly. They're re-added server-side regardless.
            const persisted = Array.from(selected).filter((name) => !isAlwaysRetained(name))
            onSave(persisted.length > 0 ? persisted : null)
        }
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`Select columns to sync — ${schema?.name ?? ''}`}
            description={
                available.length === 0
                    ? "Refresh schemas first to see this table's columns."
                    : 'Primary-key and incremental columns are always synced and cannot be unchecked.'
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={setSyncAll}>
                        Sync all columns
                    </LemonButton>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSave}
                        disabledReason={available.length === 0 ? 'No columns discovered' : undefined}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2 min-w-[420px]">
                <LemonInput
                    type="search"
                    placeholder="Filter columns"
                    size="small"
                    value={filter}
                    onChange={setFilter}
                />
                <div className="max-h-96 overflow-y-auto border rounded">
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
                    {filteredColumns.length === 0 && (
                        <div className="text-center text-muted-alt py-6 text-sm">No columns match.</div>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
