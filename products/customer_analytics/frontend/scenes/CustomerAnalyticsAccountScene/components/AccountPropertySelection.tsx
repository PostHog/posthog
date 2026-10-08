import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { AccountPropertyConfiguratorItem } from './AccountPropertyConfiguratorItem'
import { AccountPropertyOption, MAX_PINNED_ACCOUNT_PROPERTIES } from './accountPropertyTypes'

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
    const optionsByKey = new Map(options.map((option) => [option.key, option]))
    const selectedOptions = selectedKeys.map(
        (key): AccountPropertyOption =>
            optionsByKey.get(key) ?? {
                key,
                label: key,
                kind: key.startsWith('account:')
                    ? 'account'
                    : key.startsWith('relationship:')
                      ? 'relationship'
                      : 'custom',
            }
    )
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
                        const from = selectedKeys.indexOf(String(active.id))
                        const to = selectedKeys.indexOf(String(over.id))
                        if (from < 0 || to < 0 || from === to) {
                            return
                        }
                        const reordered = [...selectedKeys]
                        const [moved] = reordered.splice(from, 1)
                        reordered.splice(to, 0, moved)
                        onChange(reordered)
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
                    const key = keys[0]
                    if (key && !saving && !limitReached && !selectedKeys.includes(key)) {
                        onChange([...selectedKeys, key])
                    }
                }}
                options={availableOptions.map((option) => ({
                    key: option.key,
                    label: option.label,
                    labelComponent: (
                        <span className="flex w-full items-center justify-between gap-2">
                            <span className="truncate">{option.label}</span>
                            <span className="text-xs text-secondary">
                                {option.kind === 'custom'
                                    ? 'Custom property'
                                    : option.kind === 'account'
                                      ? 'Account property'
                                      : 'Relationship'}
                            </span>
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
