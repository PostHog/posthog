import { useActions, useValues } from 'kea'
import { cloneElement, MouseEvent, useCallback, useEffect, useId, useRef } from 'react'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { useScrollObserver } from 'lib/hooks/useScrollObserver'
import { teamLogic } from 'scenes/teamLogic'

import { LoadTags, TagOption, tagSelectLogic } from './tagSelectLogic'
import { TagSelectMenu } from './TagSelectMenu'

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

function useTagSource(options: TagOption[] | undefined, customLoadTags: LoadTags | undefined): LoadTags {
    const { currentTeamId } = useValues(teamLogic)
    return useCallback<LoadTags>(
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
    const source = useTagSource(options, customLoadTags)

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
                    onRetry={() => loadTagPage({ search, offset: tagResults.length, loadTags: source, requestEpoch })}
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
