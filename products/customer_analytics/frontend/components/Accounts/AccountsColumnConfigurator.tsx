import './AccountsColumnConfigurator.scss'

import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPencil, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSearchableSelect, LemonTextArea, Link } from '@posthog/lemon-ui'

import { IconOpenInNew, IconTuning, SortableDragIcon } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'

import {
    ACCOUNTS_NAME_COLUMN,
    AccountColumnGroup,
    AccountColumnGroupKey,
    accountsColumnConfigLogic,
} from './accountsColumnConfigLogic'

const HOGQL_DOCS_URL = 'https://posthog.com/docs/hogql'

export function AccountsColumnConfigurator(): JSX.Element {
    const { columnConfiguratorVisible } = useValues(accountsColumnConfigLogic)
    const { showColumnConfigurator, hideColumnConfigurator } = useActions(accountsColumnConfigLogic)

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

function AccountsColumnConfiguratorModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const { selectColumns, accountsColumnGroups, databaseLoading } = useValues(accountsColumnConfigLogic)
    const { moveColumn, resetColumns, setSelectColumns, unselectColumn } = useActions(accountsColumnConfigLogic)

    const onEditColumn = (column: string, index: number): void => {
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
                    <div className="flex-1 flex flex-wrap items-center gap-2">
                        <LemonButton type="secondary" onClick={resetColumns}>
                            Reset to defaults
                        </LemonButton>
                    </div>
                    <LemonButton type="primary" onClick={onClose} data-attr="accounts-columns-done">
                        Done
                    </LemonButton>
                </>
            }
        >
            <div className="AccountsColumnConfiguratorModal">
                <div className="flex flex-col gap-4">
                    <div className="w-full">
                        <h4 className="secondary uppercase text-secondary">
                            Visible columns ({selectColumns.length}) - Drag to reorder
                        </h4>
                        <div className="SelectedColumnsList">
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
                                            dataIndex={index}
                                            onEdit={onEditColumn}
                                            onRemove={unselectColumn}
                                        />
                                    ))}
                                </SortableContext>
                            </DndContext>
                        </div>
                    </div>
                    <div className="w-full">
                        <h4 className="secondary uppercase text-secondary">Available columns</h4>
                        <AvailableColumnsPicker groups={accountsColumnGroups} loading={databaseLoading} />
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}

function SelectedAccountColumn({
    column,
    dataIndex,
    onEdit,
    onRemove,
}: {
    column: string
    dataIndex: number
    onEdit: (column: string, index: number) => void
    onRemove: (column: string) => void
}): JSX.Element {
    const { aliasToDefinition, aliasToRelationshipDefinition } = useValues(accountsColumnConfigLogic)
    const { setNodeRef, attributes, transform, transition, listeners } = useSortable({ id: column })
    const alias = extractDisplayLabel(column)
    // Custom-property and relationship columns are aliased to opaque `cp_<id>` / `rel_<id>`
    // (or legacy role keys); show the definition name instead.
    const label = aliasToDefinition[alias]?.name ?? aliasToRelationshipDefinition[alias]?.name ?? alias
    // `name` carries the row identity (account id) and external_id for the
    // Account cell — removing it would break row expansion and role updates.
    const isMandatory = column === ACCOUNTS_NAME_COLUMN

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Transform.toString(transform), transition }}
            {...attributes}
        >
            <div className="SelectedColumn" data-attr={`accounts-column-row-${label}`}>
                <span {...listeners} className="drag-handle">
                    <SortableDragIcon />
                </span>
                <span className="ml-1 truncate font-mono text-sm" title={column}>
                    {label}
                </span>
                <div className="flex-1" />
                {isMandatory ? null : (
                    <Tooltip title="Edit">
                        <LemonButton onClick={() => onEdit(column, dataIndex)} size="small">
                            <IconPencil data-attr="column-display-item-edit-icon" />
                        </LemonButton>
                    </Tooltip>
                )}
                <Tooltip title={isMandatory ? 'This column is required' : 'Remove'}>
                    <LemonButton
                        onClick={() => onRemove(column)}
                        status="danger"
                        size="small"
                        disabledReason={isMandatory ? 'This column is required' : undefined}
                    >
                        <IconX data-attr="column-display-item-remove-icon" />
                    </LemonButton>
                </Tooltip>
            </div>
        </div>
    )
}

function AvailableColumnsPicker({ groups, loading }: { groups: AccountColumnGroup[]; loading: boolean }): JSX.Element {
    const { selectColumns } = useValues(accountsColumnConfigLogic)
    const { selectColumn } = useActions(accountsColumnConfigLogic)
    const [activeGroupKey, setActiveGroupKey] = useState<AccountColumnGroupKey>('account_properties')
    const [search, setSearch] = useState('')
    const [sqlInput, setSqlInput] = useState('')

    const activeGroup = useMemo(
        () => groups.find((g) => g.key === activeGroupKey) ?? groups[0],
        [groups, activeGroupKey]
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

    const addSqlExpression = (): void => {
        const expr = sqlInput.trim()
        if (expr) {
            selectColumn(expr)
            setSqlInput('')
        }
    }

    const searchPlaceholder = activeGroup?.isFreeform
        ? 'Use the SQL expression panel below'
        : `Search ${activeGroup?.label.toLowerCase() ?? 'columns'}`

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                placeholder={searchPlaceholder}
                value={search}
                onChange={setSearch}
                disabled={activeGroup?.isFreeform}
                fullWidth
                data-attr="accounts-columns-search"
                suffix={
                    <CategoryPicker
                        groups={groups}
                        activeKey={activeGroupKey}
                        onChange={(key) => {
                            setActiveGroupKey(key)
                            setSearch('')
                        }}
                    />
                }
            />
            {activeGroup?.isFreeform ? (
                <SqlExpressionPanel value={sqlInput} onChange={setSqlInput} onAdd={addSqlExpression} />
            ) : (
                <div className="AvailableColumnsList border border-border rounded">
                    {loading && filteredOptions.length === 0 ? (
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
                                    <li key={option.expression} className="border-b border-border last:border-b-0">
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
            )}
        </div>
    )
}

function CategoryPicker({
    groups,
    activeKey,
    onChange,
}: {
    groups: AccountColumnGroup[]
    activeKey: AccountColumnGroupKey
    onChange: (key: AccountColumnGroupKey) => void
}): JSX.Element {
    return (
        <LemonSearchableSelect
            size="xsmall"
            value={activeKey}
            options={groups.map((group) => ({
                value: group.key,
                label: group.label,
                'data-attr': `accounts-columns-group-item-${group.key}`,
            }))}
            onChange={(key) => key && onChange(key as AccountColumnGroupKey)}
            searchPlaceholder="Search categories"
            dropdownPlacement="bottom-end"
            data-attr="accounts-columns-group"
        />
    )
}

function SqlExpressionPanel({
    value,
    onChange,
    onAdd,
}: {
    value: string
    onChange: (next: string) => void
    onAdd: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-3 border border-border rounded">
            <div>
                <h4 className="secondary uppercase text-secondary mb-1">SQL expression</h4>
                <LemonTextArea
                    value={value}
                    onChange={onChange}
                    placeholder="JSONExtractString(properties, 'industry') AS industry"
                    minRows={3}
                    data-attr="accounts-columns-sql"
                />
            </div>
            <div className="text-secondary text-xs whitespace-pre">
                {`Enter SQL expression, such as:
- properties.industry
- toInt(properties.\`Long Field Name\`) * 10
- concat(name, ' (', external_id, ')')`}
            </div>
            <LemonButton
                type="primary"
                fullWidth
                center
                disabledReason={!value.trim() ? 'Enter a HogQL expression' : undefined}
                onClick={onAdd}
                data-attr="accounts-columns-sql-add"
            >
                Add SQL expression
            </LemonButton>
            <div className="flex justify-end">
                <Link to={HOGQL_DOCS_URL} target="_blank" className="text-xs flex items-center gap-1">
                    Learn more about SQL <IconOpenInNew />
                </Link>
            </div>
        </div>
    )
}
