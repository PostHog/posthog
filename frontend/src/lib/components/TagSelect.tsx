import { useActions, useValues } from 'kea'
import { cloneElement, MouseEvent, useCallback, useEffect, useId, useRef } from 'react'

import {
    LemonButton,
    LemonButtonProps,
    LemonCheckbox,
    LemonDropdown,
    LemonDropdownProps,
    LemonInput,
} from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { useScrollObserver } from 'lib/hooks/useScrollObserver'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { teamLogic } from 'scenes/teamLogic'

import { LoadTags, TagOption, tagSelectLogic } from './tagSelectLogic'

const TAGS_PER_PAGE = 50

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
    const logic = tagSelectLogic({ logicKey: logicKey ?? fallbackKey })
    const {
        awaitingFirstPage,
        hasMoreTags,
        requestEpoch,
        search,
        showPopover,
        tagPageError,
        tagPageLoading,
        tagResults,
    } = useValues(logic)
    const { loadTagPage, setSearch, setShowPopover } = useActions(logic)
    const { currentTeamId } = useValues(teamLogic)

    const source = useCallback<LoadTags>(
        async (query, offset) => {
            if (options) {
                const matches = options.filter((option) => option.tag.toLowerCase().includes(query.toLowerCase()))
                return {
                    results: matches.slice(offset, offset + TAGS_PER_PAGE),
                    hasMore: offset + TAGS_PER_PAGE < matches.length,
                }
            }
            if (customLoadTags) {
                return customLoadTags(query, offset)
            }
            if (currentTeamId == null) {
                return { results: [], hasMore: false }
            }
            const params = new URLSearchParams({ search: query, limit: String(TAGS_PER_PAGE), offset: String(offset) })
            const page: PaginatedResponse<string> = await api.get(`api/projects/${currentTeamId}/tags?${params}`)
            return {
                results: page.results.map((tag) => ({ tag })),
                hasMore: page.next != null,
            }
        },
        [options, customLoadTags, currentTeamId]
    )

    useEffect(() => {
        if (showPopover) {
            loadTagPage({ search, offset: 0, loadTags: source, requestEpoch })
        }
    }, [showPopover, search, source, loadTagPage, requestEpoch])

    const loadMore = (): void => {
        if (hasMoreTags && !awaitingFirstPage && !tagPageLoading && !tagPageError) {
            loadTagPage({ search, offset: tagResults.length, loadTags: source, requestEpoch })
        }
    }
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
            className="min-w-26 max-w-48 truncate"
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
            actionable
            onVisibilityChange={setShowPopover}
            overlay={
                <div className="w-64 max-w-[min(25rem,80vw)] deprecated-space-y-2">
                    <LemonInput
                        type="search"
                        placeholder="Search tags"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    <span role="status" className="sr-only">
                        {tagPageError
                            ? "Couldn't load tags. Try again."
                            : tagPageLoading || awaitingFirstPage
                              ? 'Loading tags'
                              : displayedTags.length === 0
                                ? search
                                    ? 'No matching tags'
                                    : 'No tags'
                                : search
                                  ? `${displayedTags.length} tags shown`
                                  : ''}
                    </span>
                    <div ref={scrollRef} className="max-h-80 overflow-y-auto" data-attr={listDataAttr}>
                        <ul className="deprecated-space-y-px">
                            {displayedTags.map(({ tag, count }) => (
                                <li key={tag}>
                                    <LemonButton
                                        fullWidth
                                        role="checkbox"
                                        aria-checked={value.includes(tag)}
                                        aria-label={count === undefined ? tag : `${tag} (${count})`}
                                        tooltip={tag}
                                        size="small"
                                        onClick={() => handleToggle(tag)}
                                    >
                                        <span className="flex min-w-0 flex-1 items-center gap-2 text-left">
                                            <LemonCheckbox
                                                checked={value.includes(tag)}
                                                decorative
                                                className="pointer-events-none"
                                            />
                                            <span className="min-w-0 flex-1 truncate" title={tag}>
                                                {tag}
                                            </span>
                                            {count !== undefined && (
                                                <span className="text-muted tabular-nums">{count}</span>
                                            )}
                                        </span>
                                    </LemonButton>
                                </li>
                            ))}
                            {(tagPageLoading || awaitingFirstPage) && !tagPageError && (
                                <li className="p-1" aria-label="Loading tags">
                                    <LemonSkeleton.Row
                                        className="h-8 mb-1"
                                        repeat={displayedTags.length === 0 ? 5 : 2}
                                        fade
                                    />
                                </li>
                            )}
                            {!tagPageLoading && !awaitingFirstPage && !tagPageError && displayedTags.length === 0 && (
                                <li className="p-2 text-secondary italic">{search ? 'No matching tags' : 'No tags'}</li>
                            )}
                        </ul>
                    </div>
                    {tagPageError && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="secondary"
                            loading={tagPageLoading}
                            onClick={() =>
                                loadTagPage({ search, offset: tagResults.length, loadTags: source, requestEpoch })
                            }
                        >
                            Couldn't load tags. Try again.
                        </LemonButton>
                    )}
                    {selectedCount > 0 && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="secondary"
                            onClick={() => {
                                onChange([])
                                setShowPopover(false)
                                triggerRef.current?.focus()
                            }}
                        >
                            Clear selection
                        </LemonButton>
                    )}
                </div>
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
