import './AccountsColumnConfigurator.scss'

import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'

import { IconPencil, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSearchableSelect,
    LemonSegmentedButton,
    LemonSelect,
} from '@posthog/lemon-ui'

import { IconTuning, SortableDragIcon } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { isNumericDisplayType } from '../../scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import {
    ACCOUNTS_NAME_COLUMN,
    ALL_COLUMNS_KEY,
    AccountColumnDisplayMode,
    AccountColumnGroup,
    COLUMN_DISPLAY_WINDOW_OPTIONS,
    DEFAULT_COLUMN_DISPLAY_WINDOW_DAYS,
    PickerGroupKey,
    accountsColumnConfigLogic,
} from './accountsColumnConfigLogic'
import { accountsViewsLogic } from './accountsViewsLogic'

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
    const { selectColumns, accountsColumnGroups, databaseLoading, editingColumn, editingColumnIndex } =
        useValues(accountsColumnConfigLogic)
    const { moveColumn, resetColumns, unselectColumn, setEditingColumnIndex } = useActions(accountsColumnConfigLogic)

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
                    <SaveViewButton />
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
                                            isEditing={index === editingColumnIndex}
                                            onEdit={setEditingColumnIndex}
                                            onRemove={unselectColumn}
                                        />
                                    ))}
                                </SortableContext>
                            </DndContext>
                        </div>
                    </div>
                    {editingColumn !== null && editingColumnIndex !== null ? (
                        <ColumnEditSection
                            key={editingColumnIndex}
                            column={editingColumn}
                            onClose={() => setEditingColumnIndex(null)}
                        />
                    ) : (
                        <div className="w-full">
                            <h4 className="secondary uppercase text-secondary">Available columns</h4>
                            <AvailableColumnsPicker groups={accountsColumnGroups} loading={databaseLoading} />
                        </div>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}

// Column and display changes only persist when saved to a view; surface that path here
// so users don't have to find the view selector after configuring.
function SaveViewButton(): JSX.Element {
    const { currentView, canEditCurrentView, isDirty, viewsLoading } = useValues(accountsViewsLogic)
    const { updateView, setIsCreating } = useActions(accountsViewsLogic)
    const { hideColumnConfigurator } = useActions(accountsColumnConfigLogic)

    if (currentView && canEditCurrentView) {
        return (
            <LemonButton
                type="secondary"
                loading={viewsLoading}
                disabledReason={isDirty ? undefined : 'No changes to save'}
                onClick={() => updateView({ id: currentView.id, updates: {} })}
                data-attr="accounts-columns-update-view"
            >
                Update "{currentView.name}"
            </LemonButton>
        )
    }
    return (
        <LemonButton
            type="secondary"
            // The create-view modal is rendered by AccountsViewSelector and would stack
            // behind this one — close the configurator first so it's reachable.
            onClick={() => {
                hideColumnConfigurator()
                setIsCreating(true)
            }}
            data-attr="accounts-columns-save-view"
        >
            Save as new view
        </LemonButton>
    )
}

function ColumnEditSection({ column, onClose }: { column: string; onClose: () => void }): JSX.Element | null {
    const { aliasToDefinition } = useValues(accountsColumnConfigLogic)
    const definition = aliasToDefinition[extractDisplayLabel(column)]

    if (!definition) {
        return null
    }

    return (
        <div className="w-full flex flex-col gap-2 p-3 border border-border rounded" data-attr="accounts-column-edit">
            <div className="flex items-center justify-between">
                <h4 className="secondary uppercase text-secondary mb-0">
                    Edit column{definition ? `: ${definition.name}` : ''}
                </h4>
                <LemonButton size="small" onClick={onClose} data-attr="accounts-column-edit-close">
                    Back to available columns
                </LemonButton>
            </div>
            <CustomPropertyDisplayEditor definition={definition} />
        </div>
    )
}

function CustomPropertyDisplayEditor({ definition }: { definition: CustomPropertyDefinitionApi }): JSX.Element {
    const { columnDisplay } = useValues(accountsColumnConfigLogic)
    const { setColumnDisplay } = useActions(accountsColumnConfigLogic)
    const definitionId = definition.id
    const config = columnDisplay[definitionId] ?? null
    const isNumeric = isNumericDisplayType(definition.display_type)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-4">
                <span className="text-sm font-medium">Display as</span>
                <LemonSegmentedButton
                    size="small"
                    value={config?.mode ?? 'value'}
                    onChange={(mode) =>
                        setColumnDisplay(
                            definitionId,
                            mode === 'value'
                                ? null
                                : {
                                      mode: mode as AccountColumnDisplayMode,
                                      window_days: config?.window_days ?? DEFAULT_COLUMN_DISPLAY_WINDOW_DAYS,
                                  }
                        )
                    }
                    options={[
                        { value: 'value', label: 'Plain value' },
                        {
                            value: 'sparkline',
                            label: 'Sparkline',
                            disabledReason: isNumeric ? undefined : 'Only available for numeric properties',
                        },
                        {
                            value: 'trend',
                            label: 'Trend',
                            disabledReason: isNumeric ? undefined : 'Only available for numeric properties',
                        },
                    ]}
                    data-attr="accounts-column-display-mode"
                />
            </div>
            {config ? (
                <div className="flex items-center gap-4">
                    <span className="text-sm font-medium">Look-back window</span>
                    <LemonSelect
                        size="small"
                        value={config.window_days}
                        onChange={(window_days) =>
                            window_days != null && setColumnDisplay(definitionId, { ...config, window_days })
                        }
                        options={COLUMN_DISPLAY_WINDOW_OPTIONS.map((days) => ({
                            value: days,
                            label: `${days} days`,
                        }))}
                        data-attr="accounts-column-display-window"
                    />
                </div>
            ) : null}
            <div className="text-xs text-secondary">
                {config?.mode === 'sparkline'
                    ? 'Shows how the value changed over the look-back window.'
                    : config?.mode === 'trend'
                      ? 'Shows the current value and how much it changed over the look-back window.'
                      : 'Shows the current value.'}
            </div>
        </div>
    )
}

function SelectedAccountColumn({
    column,
    dataIndex,
    isEditing,
    onEdit,
    onRemove,
}: {
    column: string
    dataIndex: number
    isEditing: boolean
    onEdit: (index: number) => void
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
    const canEdit = !isMandatory && !!aliasToDefinition[alias]

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
                {canEdit ? (
                    <Tooltip title="Edit">
                        <LemonButton onClick={() => onEdit(dataIndex)} size="small" active={isEditing}>
                            <IconPencil data-attr="column-display-item-edit-icon" />
                        </LemonButton>
                    </Tooltip>
                ) : null}
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
    const { pickerGroupKey, pickerSearch, pickerSearchPlaceholder, filteredColumnOptions } =
        useValues(accountsColumnConfigLogic)
    const { selectColumn, setPickerGroupKey, setPickerSearch } = useActions(accountsColumnConfigLogic)

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                placeholder={pickerSearchPlaceholder}
                value={pickerSearch}
                onChange={setPickerSearch}
                fullWidth
                data-attr="accounts-columns-search"
                suffix={<CategoryPicker groups={groups} activeKey={pickerGroupKey} onChange={setPickerGroupKey} />}
            />
            <div className="AvailableColumnsList border border-border rounded">
                {loading && filteredColumnOptions.length === 0 ? (
                    <div className="p-3 text-secondary">Loading schema…</div>
                ) : filteredColumnOptions.length === 0 ? (
                    <div className="p-3 text-secondary">
                        {pickerSearch.trim() ? 'No matching columns' : 'No columns available'}
                    </div>
                ) : (
                    <ul className="m-0 p-0 list-none">
                        {filteredColumnOptions.map((option) => (
                            <li
                                key={`${option.groupLabel}::${option.expression}`}
                                className="border-b border-border last:border-b-0"
                            >
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    onClick={() => !option.isSelected && selectColumn(option.expression)}
                                    disabledReason={option.isSelected ? 'Already added' : undefined}
                                    data-attr={`accounts-column-option-${option.name}`}
                                >
                                    <span className="flex-1 font-mono">{option.name}</span>
                                    {pickerGroupKey === ALL_COLUMNS_KEY ? (
                                        <span className="ml-2 text-xs text-secondary">{option.groupLabel}</span>
                                    ) : null}
                                    {option.type ? (
                                        <span className="ml-2 text-xs text-secondary">{option.type}</span>
                                    ) : null}
                                </LemonButton>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    )
}

function CategoryPicker({
    groups,
    activeKey,
    onChange,
}: {
    groups: AccountColumnGroup[]
    activeKey: PickerGroupKey
    onChange: (key: PickerGroupKey) => void
}): JSX.Element {
    return (
        <LemonSearchableSelect
            size="xsmall"
            value={activeKey}
            options={[
                {
                    value: ALL_COLUMNS_KEY,
                    label: 'All columns',
                    'data-attr': `accounts-columns-group-item-${ALL_COLUMNS_KEY}`,
                },
                ...groups.map((group) => ({
                    value: group.key,
                    label: group.label,
                    'data-attr': `accounts-columns-group-item-${group.key}`,
                })),
            ]}
            onChange={(key) => key && onChange(key as PickerGroupKey)}
            searchPlaceholder="Search categories"
            dropdownPlacement="bottom-end"
            data-attr="accounts-columns-group"
        />
    )
}
