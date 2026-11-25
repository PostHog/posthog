import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import {
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Text,
} from '@posthog/quill'

import type { AccountPropertySelectionProps } from './AccountPropertySelection'
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
import { QuillAccountPropertyConfiguratorItem } from './QuillAccountPropertyConfiguratorItem'

export function QuillAccountPropertySelection({
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

    const addDisabledReason = saving
        ? 'Saving'
        : limitReached
          ? (limitDisabledReason ?? `You can pin up to ${MAX_PINNED_ACCOUNT_PROPERTIES} properties`)
          : undefined

    return (
        <div className="flex flex-col gap-2 min-w-0">
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Choose up to {MAX_PINNED_ACCOUNT_PROPERTIES} properties. Drag selected properties to reorder them.
            </Text>
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
                                <QuillAccountPropertyConfiguratorItem
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
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    {emptyLabel}
                </Text>
            )}
            <Combobox
                items={availableOptions}
                value={null}
                onValueChange={(option: AccountPropertyOption | null) => {
                    const added = addedAccountPropertyKeys(selectedKeys, option?.key, saving || limitReached)
                    if (added) {
                        onChange(added)
                    }
                }}
                itemToStringLabel={(option: AccountPropertyOption) => option.label}
                isItemEqualToValue={(item: AccountPropertyOption, value: AccountPropertyOption) =>
                    item.key === value.key
                }
            >
                <ComboboxInput
                    placeholder="Add a property"
                    aria-label="Available properties"
                    disabledReason={addDisabledReason}
                    data-attr="account-pinned-property-selector"
                />
                <ComboboxContent>
                    <ComboboxEmpty>No matching properties</ComboboxEmpty>
                    <ComboboxList>
                        {(option: AccountPropertyOption) => (
                            <ComboboxItem key={option.key} value={option}>
                                <span className="flex w-full items-center justify-between gap-2">
                                    <span className="truncate">{option.label}</span>
                                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                        {ACCOUNT_PROPERTY_KIND_LABELS[option.kind]}
                                    </Text>
                                </span>
                            </ComboboxItem>
                        )}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
        </div>
    )
}
