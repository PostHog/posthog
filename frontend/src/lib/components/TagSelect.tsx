import { useActions, useValues } from 'kea'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps, LemonInput } from '@posthog/lemon-ui'

import { tagSelectLogic } from './tagSelectLogic'

export type TagSelectProps = {
    defaultLabel?: string
    value: string[]
    onChange: (value: string[]) => void
    children?: (selectedTags: string[]) => LemonDropdownProps['children']
}

export function TagSelect({
    defaultLabel = 'Any tags',
    value,
    onChange,
    children,
    ...buttonProps
}: TagSelectProps & Pick<LemonButtonProps, 'type' | 'size'>): JSX.Element {
    const { filteredTags, search, showPopover } = useValues(tagSelectLogic)
    const { setSearch, setShowPopover } = useActions(tagSelectLogic)

    const _onChange = (newTags: string[]): void => {
        onChange(newTags)
    }

    const handleTagToggle = (tag: string): void => {
        const selected = new Set(value || [])
        if (selected.has(tag)) {
            selected.delete(tag)
        } else {
            selected.add(tag)
        }
        _onChange(Array.from(selected))
    }

    const handleClear = (): void => {
        _onChange([])
        setShowPopover(false)
    }

    const selectedCount = value?.length || 0
    const buttonClass = selectedCount > 0 ? 'min-w-26' : 'w-26'

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            actionable
            onVisibilityChange={setShowPopover}
            overlay={
                <div className="max-w-100 deprecated-space-y-2 overflow-hidden">
                    <LemonInput
                        type="search"
                        placeholder="Search tags"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    <ul className="deprecated-space-y-px">
                        {filteredTags.map((tag: string) => (
                            <li key={tag}>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    onClick={() => handleTagToggle(tag)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span className="flex items-center gap-2">
                                            <input
                                                type="checkbox"
                                                className="cursor-pointer"
                                                checked={value?.includes(tag) || false}
                                                readOnly
                                            />
                                            <span>{tag}</span>
                                        </span>
                                    </span>
                                </LemonButton>
                            </li>
                        ))}

                        {filteredTags.length === 0 ? (
                            <div className="p-2 text-secondary italic truncate border-t">
                                {search ? <span>No matching tags</span> : <span>No tags</span>}
                            </div>
                        ) : null}

                        {selectedCount > 0 && (
                            <>
                                <div className="my-1 border-t" />
                                <li>
                                    <LemonButton
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        onClick={handleClear}
                                        type="secondary"
                                    >
                                        Clear selection
                                    </LemonButton>
                                </li>
                            </>
                        )}
                    </ul>
                </div>
            }
        >
            {children ? (
                children(value)
            ) : (
                <LemonButton size="small" type="secondary" className={buttonClass} {...buttonProps}>
                    {selectedCount > 0 ? `${selectedCount} selected` : defaultLabel}
                </LemonButton>
            )}
        </LemonDropdown>
    )
}
