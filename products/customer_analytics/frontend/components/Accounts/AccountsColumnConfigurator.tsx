import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPencil, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { IconTuning, SortableDragIcon } from 'lib/lemon-ui/icons'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'

import { AccountColumnGroup, AccountColumnGroupKey, accountsLogic } from './accountsLogic'

export function AccountsColumnConfigurator(): JSX.Element {
    const { columnConfiguratorVisible } = useValues(accountsLogic)
    const { showColumnConfigurator, hideColumnConfigurator } = useActions(accountsLogic)

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconTuning />}
                onClick={showColumnConfigurator}
                data-attr="accounts-configure-columns"
            >
                Configure columns
            </LemonButton>
            <AccountsColumnConfiguratorModal isOpen={columnConfiguratorVisible} onClose={hideColumnConfigurator} />
        </>
    )
}

function AccountsColumnConfiguratorModal({
    isOpen,
    onClose,
}: {
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const { selectColumns, accountsColumnGroups, databaseLoading } = useValues(accountsLogic)
    const { saveColumns, moveColumn, resetColumns, setSelectColumns } = useActions(accountsLogic)

    const editColumn = (column: string, index: number): void => {
        const next = window.prompt('Edit column', column)
        if (next !== null && next !== '') {
            setSelectColumns(selectColumns.map((c, i) => (i === index ? next : c)))
        }
    }

    return (
        <LemonModal
            isOpen={isOpen}
            title="Configure columns"
            onClose={onClose}
            className="w-full max-w-248"
            footer={
                <>
                    <div className="flex-1">
                        <LemonButton type="secondary" onClick={resetColumns}>
                            Reset to defaults
                        </LemonButton>
                    </div>
                    <LemonButton type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            saveColumns()
                            onClose()
                        }}
                        data-attr="accounts-columns-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="w-full">
                    <h4 className="secondary uppercase text-secondary">
                        Visible columns ({selectColumns.length}) - Drag to reorder
                    </h4>
                    <DndContext
                        onDragEnd={({ active, over }) => {
                            if (over && active.id !== over.id) {
                                moveColumn(
                                    selectColumns.indexOf(active.id.toString()),
                                    selectColumns.indexOf(over.id.toString())
                                )
                            }
                        }}
                        modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                    >
                        <SortableContext items={selectColumns} strategy={verticalListSortingStrategy}>
                            {selectColumns.map((column, index) => (
                                <SelectedAccountColumn
                                    key={column}
                                    column={column}
                                    onEdit={() => editColumn(column, index)}
                                />
                            ))}
                        </SortableContext>
                    </DndContext>
                </div>
                <div className="w-full">
                    <h4 className="secondary uppercase text-secondary">Available columns</h4>
                    <AvailableColumnsPicker groups={accountsColumnGroups} loading={databaseLoading} />
                </div>
            </div>
        </LemonModal>
    )
}

function SelectedAccountColumn({ column, onEdit }: { column: string; onEdit: () => void }): JSX.Element {
    const { unselectColumn } = useActions(accountsLogic)
    const { setNodeRef, attributes, transform, transition, listeners } = useSortable({ id: column })
    const label = extractDisplayLabel(column)

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Transform.toString(transform), transition }}
            {...attributes}
            className="flex items-center gap-2 px-2 py-1 border-b border-border last:border-b-0"
            data-attr={`accounts-column-row-${label}`}
        >
            <span {...listeners} className="cursor-grab text-secondary flex items-center">
                <SortableDragIcon />
            </span>
            <span className="flex-1 truncate font-mono text-sm" title={column}>
                {label}
            </span>
            <LemonButton size="small" onClick={onEdit} tooltip="Edit expression">
                <IconPencil />
            </LemonButton>
            <LemonButton size="small" status="danger" onClick={() => unselectColumn(column)} tooltip="Remove column">
                <IconX />
            </LemonButton>
        </div>
    )
}

function AvailableColumnsPicker({
    groups,
    loading,
}: {
    groups: AccountColumnGroup[]
    loading: boolean
}): JSX.Element {
    const { selectColumns } = useValues(accountsLogic)
    const { selectColumn } = useActions(accountsLogic)
    const [activeGroupKey, setActiveGroupKey] = useState<AccountColumnGroupKey>('account_properties')
    const [search, setSearch] = useState('')
    const [sqlInput, setSqlInput] = useState('')

    const activeGroup = useMemo(
        () => groups.find((g) => g.key === activeGroupKey) ?? groups[0],
        [groups, activeGroupKey]
    )

    const selectOptions = useMemo(
        () =>
            groups.map((g) => ({
                value: g.key,
                label: g.label,
            })),
        [groups]
    )

    const filteredOptions = useMemo(() => {
        if (!activeGroup || activeGroup.isFreeform) {
            return []
        }
        const query = search.trim().toLowerCase()
        if (!query) {
            return activeGroup.options
        }
        return activeGroup.options.filter((option) => option.name.toLowerCase().includes(query))
    }, [activeGroup, search])

    const isSelected = (expression: string): boolean => selectColumns.includes(expression)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <LemonInput
                    placeholder={activeGroup?.isFreeform ? 'SQL expression mode' : 'Search columns'}
                    value={search}
                    onChange={setSearch}
                    disabled={activeGroup?.isFreeform}
                    fullWidth
                    data-attr="accounts-columns-search"
                />
                <LemonSelect<AccountColumnGroupKey>
                    value={activeGroupKey}
                    options={selectOptions}
                    onChange={(value) => value && setActiveGroupKey(value)}
                    data-attr="accounts-columns-group"
                />
            </div>
            <div className="h-[min(360px,50vh)] overflow-y-auto border border-border rounded">
                {activeGroup?.isFreeform ? (
                    <div className="flex flex-col gap-2 p-3">
                        <LemonTextArea
                            value={sqlInput}
                            onChange={setSqlInput}
                            placeholder="JSONExtractString(properties, 'industry') AS industry"
                            minRows={3}
                            data-attr="accounts-columns-sql"
                        />
                        <div>
                            <LemonButton
                                type="primary"
                                size="small"
                                disabledReason={!sqlInput.trim() ? 'Enter a HogQL expression' : undefined}
                                onClick={() => {
                                    const expr = sqlInput.trim()
                                    if (expr) {
                                        selectColumn(expr)
                                        setSqlInput('')
                                    }
                                }}
                            >
                                Add column
                            </LemonButton>
                        </div>
                    </div>
                ) : loading && filteredOptions.length === 0 ? (
                    <div className="p-3 text-secondary">Loading schema…</div>
                ) : filteredOptions.length === 0 ? (
                    <div className="p-3 text-secondary">
                        {search.trim() ? 'No matching columns' : 'No columns available'}
                    </div>
                ) : (
                    <ul className="m-0 p-0 list-none">
                        {filteredOptions.map((option) => {
                            const already = isSelected(option.expression)
                            return (
                                <li
                                    key={option.expression}
                                    className="border-b border-border last:border-b-0"
                                >
                                    <LemonButton
                                        fullWidth
                                        size="small"
                                        onClick={() => !already && selectColumn(option.expression)}
                                        disabledReason={already ? 'Already added' : undefined}
                                        data-attr={`accounts-column-option-${option.name}`}
                                    >
                                        <span className="flex-1 font-mono">{option.name}</span>
                                        {option.type ? (
                                            <span className="ml-2 text-xs text-secondary">{option.type}</span>
                                        ) : null}
                                    </LemonButton>
                                </li>
                            )
                        })}
                    </ul>
                )}
            </div>
        </div>
    )
}
