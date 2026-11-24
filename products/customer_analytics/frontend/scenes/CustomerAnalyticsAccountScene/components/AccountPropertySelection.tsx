import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { AccountPropertyConfiguratorItem } from './AccountPropertyConfiguratorItem'
import {
    ACCOUNT_PROPERTY_KIND_LABELS,
    AccountPropertyOption,
    MAX_PINNED_ACCOUNT_PROPERTIES,
} from './accountPropertyTypes'
import {
    addedAccountPropertyKeys,
    reorderedAccountPropertyKeys,
    selectedAccountPropertyOptions,
} from './pinnedAccountPropertyKeys'

export interface AccountPropertySelectionProps {
    options: AccountPropertyOption[]
    selectedKeys: string[]
    saving?: boolean
    onChange: (keys: string[]) => void
    emptyLabel?: string
    limitDisabledReason?: string
}

export function AccountPropertySelection({
    options,
    selectedKeys,
    saving = false,
    onChange,
    emptyLabel = 'No properties pinned.',
    limitDisabledReason,
}: AccountPropertySelectionProps): JSX.Element {
    const selectedOptions = selectedAccountPropertyOptions(options, selectedKeys)
    const availableOptions = options.filter((option) => !selectedKeys.includes(option.key))
    const limitReached = selectedKeys.length >= MAX_PINNED_ACCOUNT_PROPERTIES
    return (
        <div className="flex flex-col gap-2 min-w-0">
            <p className="text-sm text-secondary mb-0">
                Choose up to {MAX_PINNED_ACCOUNT_PROPERTIES} properties. Drag selected properties to reorder them.
            </p>
            {selectedOptions.length > 0 ? (
                <DndContext
                    modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                    onDragEnd={({ active, over }) => {
                        if (saving || !over) {
                            return
                        }
                        const reordered = reorderedAccountPropertyKeys(selectedKeys, String(active.id), String(over.id))
                        if (reordered) {
                            onChange(reordered)
                        }
                    }}
                >
                    <SortableContext items={selectedKeys} strategy={verticalListSortingStrategy}>
                        <div
                            className="flex max-h-80 flex-col gap-1 overflow-y-auto"
                            data-attr="account-pinned-properties-list"
                        >
                            {selectedOptions.map((option) => (
                                <AccountPropertyConfiguratorItem
                                    key={option.key}
                                    option={option}
                                    disabled={saving}
                                    onRemove={() => onChange(selectedKeys.filter((key) => key !== option.key))}
                                />
                            ))}
                        </div>
                    </SortableContext>
                </DndContext>
            ) : (
                <span className="text-sm text-muted">{emptyLabel}</span>
            )}
            <LemonInputSelect
                mode="single"
                limit={1}
                value={[]}
                onChange={(keys) => {
                    const added = addedAccountPropertyKeys(selectedKeys, keys[0], saving || limitReached)
                    if (added) {
                        onChange(added)
                    }
                }}
                options={availableOptions.map((option) => ({
                    key: option.key,
                    label: option.label,
                    labelComponent: (
                        <span className="flex w-full items-center justify-between gap-2">
                            <span className="truncate">{option.label}</span>
                            <span className="text-xs text-secondary">{ACCOUNT_PROPERTY_KIND_LABELS[option.kind]}</span>
                        </span>
                    ),
                }))}
                placeholder="Add a property"
                title="Available properties"
                fullWidth
                disabledReason={
                    saving
                        ? 'Saving'
                        : limitReached
                          ? (limitDisabledReason ?? `You can pin up to ${MAX_PINNED_ACCOUNT_PROPERTIES} properties`)
                          : undefined
                }
                data-attr="account-pinned-property-selector"
            />
        </div>
    )
}
