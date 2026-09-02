import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CSSProperties, useId } from 'react'
import { List } from 'react-window'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps, LemonInput } from '@posthog/lemon-ui'

import { tagSelectLogic } from './tagSelectLogic'

/** Matches the height of a `size="small"` LemonButton row. */
const TAG_OPTION_HEIGHT = 33
const MAX_TAG_LIST_HEIGHT = 396
/** Above this many options the list is windowed, so a project with thousands of tags still opens instantly. */
const VIRTUALIZE_ABOVE = 100

export type TagSelectProps = {
    defaultLabel?: string
    value: string[]
    onChange: (value: string[]) => void
    children?: (selectedTags: string[]) => LemonDropdownProps['children']
    /** Distinguishes the logic instance so multiple selects on one page keep independent open/search state. */
    logicKey?: string
}

interface TagOptionRowProps {
    tags: string[]
    selectedTags: string[]
    onToggle: (tag: string) => void
}

function TagOption({
    tag,
    isSelected,
    onToggle,
    style,
}: {
    tag: string
    isSelected: boolean
    onToggle: (tag: string) => void
    style?: CSSProperties
}): JSX.Element {
    return (
        <LemonButton style={style} fullWidth role="menuitem" size="small" onClick={() => onToggle(tag)}>
            <span className="flex items-center justify-between gap-2 flex-1">
                <span className="flex items-center gap-2 max-w-full">
                    <input type="checkbox" className="cursor-pointer" checked={isSelected} readOnly />
                    <span className="truncate">{tag}</span>
                </span>
            </span>
        </LemonButton>
    )
}

function VirtualizedTagOptionRow({
    index,
    style,
    tags,
    selectedTags,
    onToggle,
}: {
    index: number
    style: CSSProperties
} & TagOptionRowProps): JSX.Element {
    const tag = tags[index]
    return <TagOption tag={tag} isSelected={selectedTags.includes(tag)} onToggle={onToggle} style={style} />
}

export function TagSelect({
    defaultLabel = 'Any tags',
    value,
    onChange,
    children,
    logicKey,
    ...buttonProps
}: TagSelectProps & Pick<LemonButtonProps, 'type' | 'size'>): JSX.Element {
    const fallbackKey = useId()
    const logic = tagSelectLogic({ logicKey: logicKey ?? fallbackKey })
    const { filteredTags, search, showPopover } = useValues(logic)
    const { setSearch, setShowPopover } = useActions(logic)

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
    // Windowed rows have no intrinsic width, so the overlay takes a fixed one instead of hugging its content
    const isVirtualized = filteredTags.length > VIRTUALIZE_ABOVE

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            actionable
            onVisibilityChange={setShowPopover}
            overlay={
                <div className={clsx('deprecated-space-y-2', isVirtualized ? 'w-100' : 'max-w-100')}>
                    <LemonInput
                        type="search"
                        placeholder="Search tags"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                        className="max-w-full"
                    />

                    {filteredTags.length === 0 ? (
                        <div className="p-2 text-secondary italic truncate border-t">
                            {search ? <span>No matching tags</span> : <span>No tags</span>}
                        </div>
                    ) : isVirtualized ? (
                        <List<TagOptionRowProps>
                            defaultHeight={MAX_TAG_LIST_HEIGHT}
                            style={{
                                width: '100%',
                                height: Math.min(filteredTags.length * TAG_OPTION_HEIGHT, MAX_TAG_LIST_HEIGHT),
                            }}
                            rowCount={filteredTags.length}
                            rowHeight={TAG_OPTION_HEIGHT}
                            rowComponent={VirtualizedTagOptionRow}
                            rowProps={{
                                tags: filteredTags,
                                selectedTags: value || [],
                                onToggle: handleTagToggle,
                            }}
                        />
                    ) : (
                        <ul className="deprecated-space-y-px">
                            {filteredTags.map((tag: string) => (
                                <li key={tag}>
                                    <TagOption
                                        tag={tag}
                                        isSelected={value?.includes(tag) || false}
                                        onToggle={handleTagToggle}
                                    />
                                </li>
                            ))}
                        </ul>
                    )}

                    {selectedCount > 0 && (
                        <>
                            <div className="my-1 border-t" />
                            <LemonButton fullWidth role="menuitem" size="small" onClick={handleClear} type="secondary">
                                Clear selection
                            </LemonButton>
                        </>
                    )}
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
