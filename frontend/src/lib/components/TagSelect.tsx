import { cloneElement, MouseEvent, useId, useRef } from 'react'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps } from '@posthog/lemon-ui'

import { useScrollObserver } from 'lib/hooks/useScrollObserver'

import { LoadTags, TagOption } from './tagSelectLogic'
import { TagSelectMenu } from './TagSelectMenu'
import { useTagPages, useTagSource } from './useTagPages'

export type TagSelectProps = {
    defaultLabel?: string
    value: string[]
    onChange: (value: string[]) => void
    children?: (selectedTags: string[]) => LemonDropdownProps['children']
    logicKey?: string
    listDataAttr?: string
    options?: TagOption[]
    loadTags?: LoadTags
    borderless?: boolean
}

export function TagSelect({
    defaultLabel = 'Any tags',
    value,
    onChange,
    children,
    logicKey,
    listDataAttr,
    options,
    loadTags: customLoadTags,
    borderless = false,
    ...buttonProps
}: TagSelectProps & Pick<LemonButtonProps, 'type' | 'size' | 'aria-label'>): JSX.Element {
    const fallbackKey = useId()
    const triggerRef = useRef<HTMLElement | null>(null)
    const source = useTagSource(options, customLoadTags)
    const {
        tags: tagResults,
        search,
        open: showPopover,
        awaitingFirstPage,
        pageLoading: tagPageLoading,
        error: tagPageError,
        setOpen: setShowPopover,
        setSearch,
        loadMore,
        retry,
    } = useTagPages(logicKey ?? fallbackKey, source)
    const scrollRef = useScrollObserver({ onScrollBottom: loadMore })
    const displayedTags: TagOption[] = search
        ? tagResults
        : [
              ...value
                  .filter((tag) => !tagResults.some((option) => option.tag === tag))
                  .map((tag) => options?.find((option) => option.tag === tag) ?? { tag }),
              ...tagResults,
          ]

    const handleToggle = (tag: string): void => {
        onChange(value.includes(tag) ? value.filter((selected) => selected !== tag) : [...value, tag])
    }

    const selectedCount = value.length
    const trigger = children ? (
        children(value)
    ) : (
        <LemonButton
            size="small"
            type="secondary"
            active={selectedCount > 0}
            status={borderless && selectedCount === 0 ? 'alt' : 'default'}
            className="min-w-26 max-w-48"
            truncate
            {...buttonProps}
        >
            {selectedCount === 0 ? defaultLabel : selectedCount === 1 ? value[0] : `${selectedCount} tags`}
        </LemonButton>
    )
    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            padded={false}
            actionable
            onVisibilityChange={setShowPopover}
            overlay={
                <TagSelectMenu
                    search={search}
                    setSearch={setSearch}
                    displayedTags={displayedTags}
                    value={value}
                    awaitingFirstPage={awaitingFirstPage}
                    tagPageLoading={tagPageLoading}
                    tagPageError={tagPageError}
                    listDataAttr={listDataAttr}
                    scrollRef={scrollRef}
                    onToggle={handleToggle}
                    onRetry={retry}
                    onClear={() => {
                        onChange([])
                        setShowPopover(false)
                        triggerRef.current?.focus()
                    }}
                />
            }
        >
            {trigger &&
                cloneElement(trigger, {
                    onClick: (event: MouseEvent<HTMLElement>): void => {
                        triggerRef.current = event.currentTarget
                        trigger.props.onClick?.(event)
                    },
                })}
        </LemonDropdown>
    )
}
