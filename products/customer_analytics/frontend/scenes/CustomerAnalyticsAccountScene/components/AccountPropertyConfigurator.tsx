import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import { LemonButton, LemonInputSelect, LemonModal } from '@posthog/lemon-ui'

import { AccountPropertyConfiguratorItem } from './AccountPropertyConfiguratorItem'
import { AccountPropertyOption, MAX_PINNED_ACCOUNT_PROPERTIES } from './accountPropertyTypes'

export interface AccountPropertyConfiguratorProps {
    isOpen: boolean
    options: AccountPropertyOption[]
    pinnedPropertyKeys: string[]
    saving?: boolean
    onChange: (pinnedPropertyKeys: string[]) => void
    onSave: (pinnedPropertyKeys: string[]) => void
    onCancel: () => void
    saveDisabledReason?: string
}

export function AccountPropertyConfigurator({
    isOpen,
    options,
    pinnedPropertyKeys,
    saving = false,
    onChange,
    onSave,
    onCancel,
    saveDisabledReason,
}: AccountPropertyConfiguratorProps): JSX.Element {
    const optionsByKey = new Map(options.map((option) => [option.key, option]))
    const selectedOptions = pinnedPropertyKeys.map(
        (key): AccountPropertyOption =>
            optionsByKey.get(key) ?? {
                key,
                label: key,
                kind: 'custom',
            }
    )
    const availableOptions = options.filter((option) => !pinnedPropertyKeys.includes(option.key))
    const pinLimitReached = pinnedPropertyKeys.length >= MAX_PINNED_ACCOUNT_PROPERTIES

    const addPinnedProperty = (keys: string[]): void => {
        const key = keys[0]
        if (key && !pinLimitReached && !pinnedPropertyKeys.includes(key)) {
            onChange([...pinnedPropertyKeys, key])
        }
    }

    const movePinnedProperty = (activeKey: string, overKey: string): void => {
        const fromIndex = pinnedPropertyKeys.indexOf(activeKey)
        const toIndex = pinnedPropertyKeys.indexOf(overKey)
        if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) {
            return
        }
        const reordered = [...pinnedPropertyKeys]
        const [moved] = reordered.splice(fromIndex, 1)
        reordered.splice(toIndex, 0, moved)
        onChange(reordered)
    }

    return (
        <LemonModal
            isOpen={isOpen}
            title="Pin properties"
            onClose={onCancel}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onCancel} data-attr="account-pinned-properties-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => onSave(pinnedPropertyKeys)}
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        data-attr="account-pinned-properties-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2 min-w-80">
                <p className="text-sm text-secondary mb-0">
                    Choose up to {MAX_PINNED_ACCOUNT_PROPERTIES} properties. Drag selected properties to reorder them.
                </p>
                {selectedOptions.length > 0 ? (
                    <DndContext
                        onDragEnd={({ active, over }) => {
                            if (over) {
                                movePinnedProperty(String(active.id), String(over.id))
                            }
                        }}
                        modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                    >
                        <SortableContext items={pinnedPropertyKeys} strategy={verticalListSortingStrategy}>
                            <div
                                className="flex max-h-80 flex-col gap-1 overflow-y-auto"
                                data-attr="account-pinned-properties-list"
                            >
                                {selectedOptions.map((option) => (
                                    <AccountPropertyConfiguratorItem
                                        key={option.key}
                                        option={option}
                                        disabled={saving}
                                        onRemove={() =>
                                            onChange(pinnedPropertyKeys.filter((key) => key !== option.key))
                                        }
                                    />
                                ))}
                            </div>
                        </SortableContext>
                    </DndContext>
                ) : (
                    <span className="text-sm text-muted">No properties pinned.</span>
                )}
                <LemonInputSelect
                    mode="single"
                    limit={1}
                    value={[]}
                    onChange={addPinnedProperty}
                    options={availableOptions.map((option) => ({
                        key: option.key,
                        label: option.label,
                        labelComponent: (
                            <span className="flex w-full items-center justify-between gap-2">
                                <span className="truncate">{option.label}</span>
                                <span className="text-xs text-secondary">
                                    {option.kind === 'custom' ? 'Custom property' : 'Relationship'}
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
                            : pinLimitReached
                              ? `You can pin up to ${MAX_PINNED_ACCOUNT_PROPERTIES} properties`
                              : undefined
                    }
                    data-attr="account-pinned-property-selector"
                />
            </div>
        </LemonModal>
    )
}
