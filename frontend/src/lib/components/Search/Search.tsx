import { Autocomplete } from '@base-ui/react/autocomplete'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { router } from 'kea-router'
import {
    type MutableRefObject,
    type ReactNode,
    type RefObject,
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

import { IconSearch, IconX } from '@posthog/icons'
import { LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuGroup, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import { Label } from 'lib/ui/Label/Label'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { ProductIconWrapper, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { fileSystemTypes } from '~/products'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { RECENTS_LIMIT, SearchItem, SearchLogicProps, searchLogic } from './searchLogic'
import { formatRelativeTimeShort, getCategoryDisplayName } from './utils'

// ============================================================================
// Constants
// ============================================================================

const PLACEHOLDER_OPTIONS = [
    'insights...',
    'dashboards...',
    'feature flags...',
    'experiments...',
    'surveys...',
    'notebooks...',
    'cohorts...',
    'persons...',
    'recordings filters...',
    'workflows...',
    'early access features...',
    'events...',
    'properties...',
    'actions...',
    'groups...',
    'cohorts...',
]

const PLACEHOLDER_CYCLE_INTERVAL = 3000

// ============================================================================
// Hooks
// ============================================================================

const useRotatingPlaceholder = (isActive: boolean): { text: string; isVisible: boolean } => {
    const [index, setIndex] = useState(0)
    const [isVisible, setIsVisible] = useState(true)

    useEffect(() => {
        if (!isActive) {
            setIndex(0)
            setIsVisible(true)
            return
        }

        let timeoutId: ReturnType<typeof setTimeout> | undefined

        const interval = setInterval(() => {
            setIsVisible(false)
            timeoutId = setTimeout(() => {
                setIndex((prev) => (prev + 1) % PLACEHOLDER_OPTIONS.length)
                setIsVisible(true)
            }, 200)
        }, PLACEHOLDER_CYCLE_INTERVAL)

        return () => {
            clearInterval(interval)
            if (timeoutId !== undefined) {
                clearTimeout(timeoutId)
            }
        }
    }, [isActive])

    return { text: PLACEHOLDER_OPTIONS[index], isVisible }
}

// ============================================================================
// Helpers
// ============================================================================

const getItemTypeDisplayName = (type: string | null | undefined): string | null => {
    if (!type) {
        return null
    }

    // Check fileSystemTypes manifest first
    if (type in fileSystemTypes) {
        return (fileSystemTypes as Record<string, { name?: string }>)[type]?.name ?? null
    }

    // Handle insight subtypes (e.g., 'insight/funnels' -> 'Funnel')
    if (type.startsWith('insight/')) {
        const subtype = type.slice(8) // Remove 'insight/' prefix
        const insightDisplayNames: Record<string, string> = {
            funnels: 'Funnel',
            trends: 'Trend',
            retention: 'Retention',
            paths: 'Paths',
            lifecycle: 'Lifecycle',
            stickiness: 'Stickiness',
            hog: 'SQL insight',
        }
        return insightDisplayNames[subtype] ?? null
    }

    // Fallback for types not in the manifest
    const fallbackDisplayNames: Record<string, string> = {
        query: 'SQL query',
        product_analytics: 'Product analytics',
        web_analytics: 'Web analytics',
        llm_analytics: 'LLM analytics',
        revenue_analytics: 'Revenue analytics',
        marketing_analytics: 'Marketing analytics',
        session_replay: 'Session replay',
        error_tracking: 'Error tracking',
        data_warehouse: 'Data warehouse',
        data_pipeline: 'Data pipeline',
        annotation: 'Annotation',
        event_definition: 'Event',
        property_definition: 'Property',
        person: 'Person',
        persons: 'Person',
        user: 'User',
        group: 'Group',
        heatmap: 'Heatmap',
        sql_editor: 'SQL query',
        logs: 'Logs',
        alert: 'Alert',
        folder: 'Folder',
        hog_flow: 'Workflow',
    }
    return fallbackDisplayNames[type] ?? null
}

const getIconForItem = (item: SearchItem): ReactNode => {
    if (item.icon) {
        return item.icon
    }
    let itemType = item.itemType || item.record?.type
    // Normalize types for icon lookup
    if (itemType === 'person') {
        itemType = 'persons'
    } else if (itemType === 'hog_flow') {
        itemType = 'workflows'
    }
    if (itemType) {
        // Handle iconColor which may be a single-element array or tuple
        const rawColor = item.record?.iconColor as string[] | undefined
        const colorOverride: [string, string] | undefined = rawColor
            ? rawColor.length === 1
                ? [rawColor[0], rawColor[0]]
                : [rawColor[0], rawColor[1]]
            : undefined
        return (
            <ProductIconWrapper type={itemType as string} colorOverride={colorOverride}>
                {iconForType(itemType as FileSystemIconType, colorOverride)}
            </ProductIconWrapper>
        )
    }
    return null
}

const commandItemToTreeDataItem = (item: SearchItem): TreeDataItem => {
    return {
        id: item.id,
        name: item.name,
        record: {
            ...item.record,
            href: item.href,
            path: item.name,
        },
    }
}

// ============================================================================
// Context
// ============================================================================

interface SearchContextValue {
    searchValue: string
    setSearchValue: (value: string) => void
    filteredItems: SearchItem[]
    groupedItems: { category: string; items: SearchItem[]; isLoading?: boolean }[]
    isSearching: boolean
    isActive: boolean
    inputRef: RefObject<HTMLInputElement>
    handleItemClick: (item: SearchItem) => void
    showAskAiLink: boolean
    onAskAiClick?: () => void
    highlightedItemRef: MutableRefObject<SearchItem | null>
}

const SearchContext = createContext<SearchContextValue | null>(null)

const useSearchContext = (): SearchContextValue => {
    const context = useContext(SearchContext)
    if (!context) {
        throw new Error('Search compound components must be used within Search.Root')
    }
    return context
}

// ============================================================================
// Search.Root
// ============================================================================

export interface SearchRootProps {
    children: ReactNode
    /** Unique key to identify this search instance (e.g., 'command', 'new-tab') */
    logicKey?: SearchLogicProps['logicKey']
    /** Whether the search is active (for placeholder animation) */
    isActive?: boolean
    /** Callback when an item is selected */
    onItemSelect?: (item: SearchItem) => void
    /** Whether to show the Ask AI link */
    showAskAiLink?: boolean
    /** Callback when Ask AI is clicked */
    onAskAiClick?: () => void
    /** Custom class for the container */
    className?: string
}

function SearchRoot({
    children,
    logicKey = 'default',
    isActive = true,
    onItemSelect,
    showAskAiLink = true,
    onAskAiClick,
    className = '',
}: SearchRootProps): JSX.Element {
    const { allCategories, isSearching } = useValues(searchLogic({ logicKey }))
    const { setSearch } = useActions(searchLogic({ logicKey }))

    const [searchValue, setSearchValue] = useState('')
    const inputRef = useRef<HTMLInputElement>(null!)
    const actionsRef = useRef<Autocomplete.Root.Actions>(null)
    const highlightedItemRef = useRef<SearchItem | null>(null)

    const allItems = useMemo(() => {
        const items: SearchItem[] = []
        for (const category of allCategories) {
            items.push(...category.items)
        }
        return items
    }, [allCategories])

    // Compute filteredItems synchronously to avoid render gap between loading and content
    const filteredItems = useMemo(() => {
        if (searchValue.trim()) {
            const searchLower = searchValue.toLowerCase()
            return allItems.filter((item) => {
                // Filter recents and apps by name (client-side filtering)
                if (item.category === 'recents' || item.category === 'apps') {
                    const name = (item.displayName || item.name || '').toLowerCase()
                    return name.includes(searchLower)
                }
                // Other categories come from server search, keep all
                return true
            })
        }
        // When not searching, show recents and apps
        return allItems.filter((item) => item.category === 'recents' || item.category === 'apps')
    }, [allItems, searchValue])

    useEffect(() => {
        if (!isActive) {
            return
        }
        setSearch(searchValue)
    }, [searchValue, setSearch, isActive])

    useEffect(() => {
        if (isActive && inputRef.current) {
            setTimeout(() => {
                inputRef.current?.focus()
            }, 50)
        }
    }, [isActive])

    useEffect(() => {
        if (!isActive) {
            setSearchValue('')
            setSearch('')
        }
    }, [isActive, setSearch])

    const handleItemClick = useCallback(
        (item: SearchItem) => {
            if (onItemSelect) {
                onItemSelect(item)
            } else if (item.href) {
                router.actions.push(item.href)
            }
        },
        [onItemSelect]
    )

    const groupedItems = useMemo(() => {
        const groups: { category: string; items: SearchItem[]; isLoading?: boolean }[] = []
        const categoryMap = new Map<string, SearchItem[]>()

        for (const item of filteredItems) {
            const existing = categoryMap.get(item.category)
            if (existing) {
                existing.push(item)
            } else {
                categoryMap.set(item.category, [item])
            }
        }

        // Build loading state lookup from allCategories
        const loadingByCategory = new Map<string, boolean>()
        for (const cat of allCategories) {
            loadingByCategory.set(cat.key, cat.isLoading ?? false)
        }

        // Fixed order: recents first, then apps, then create, then everything else
        const orderedCategories = ['recents', 'apps', 'create']
        const hasSearchValue = searchValue.trim().length > 0

        for (const category of orderedCategories) {
            const items = categoryMap.get(category) ?? []
            const isLoading = loadingByCategory.get(category) ?? false

            // When searching: hide empty groups (unless still loading)
            // When not searching: always show recents/apps (with skeleton if loading)
            // "create" is only shown when searching
            const shouldShow = hasSearchValue
                ? items.length > 0 || isLoading
                : category === 'recents' || category === 'apps'

            if (shouldShow) {
                groups.push({ category, items, isLoading })
            }
        }

        // Add remaining categories
        for (const [category, items] of categoryMap) {
            if (!orderedCategories.includes(category)) {
                groups.push({ category, items, isLoading: loadingByCategory.get(category) })
            }
        }

        return groups
    }, [filteredItems, allCategories, searchValue])

    const contextValue: SearchContextValue = useMemo(
        () => ({
            searchValue,
            setSearchValue,
            filteredItems,
            groupedItems,
            isSearching,
            isActive,
            inputRef,
            handleItemClick,
            showAskAiLink,
            onAskAiClick,
            highlightedItemRef,
        }),
        [searchValue, filteredItems, groupedItems, isSearching, isActive, handleItemClick, showAskAiLink, onAskAiClick]
    )

    return (
        <SearchContext.Provider value={contextValue}>
            <div
                className={`flex flex-col overflow-hidden ${className} group/colorful-product-icons colorful-product-icons-true`}
            >
                <Autocomplete.Root
                    items={filteredItems}
                    filter={null}
                    itemToStringValue={(item) => item?.name ?? ''}
                    actionsRef={actionsRef}
                    inline
                    autoHighlight="always"
                    openOnInputClick={false}
                    defaultOpen
                >
                    {children}
                </Autocomplete.Root>
            </div>
        </SearchContext.Provider>
    )
}

// ============================================================================
// Search.Input
// ============================================================================

export interface SearchInputProps {
    autoFocus?: boolean
    className?: string
}

function SearchInput({ autoFocus, className }: SearchInputProps): JSX.Element {
    const { searchValue, setSearchValue, isActive, inputRef, showAskAiLink, onAskAiClick, highlightedItemRef } =
        useSearchContext()

    const { text: placeholderText, isVisible: placeholderVisible } = useRotatingPlaceholder(isActive && !searchValue)

    const handleInputChange = useCallback(
        (value: string) => {
            setSearchValue(value)
        },
        [setSearchValue]
    )

    const handleAskAiLinkClick = useCallback(() => {
        onAskAiClick?.()
    }, [onAskAiClick])

    const handleInputKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === 'Enter' && e.shiftKey) {
                e.preventDefault()
                e.stopPropagation()
                const item = highlightedItemRef.current
                if (item?.href) {
                    newInternalTab(item.href)
                }
            }
        },
        [highlightedItemRef]
    )

    useEffect(() => {
        if (autoFocus && inputRef.current) {
            setTimeout(() => {
                inputRef.current?.focus()
            }, 50)
        }
    }, [autoFocus, inputRef])

    return (
        <div className={cn('p-1 space-y-2', className)}>
            <label
                htmlFor="app-autocomplete-search"
                className="group input-like flex gap-1 items-center relative w-full bg-fill-input border border-primary focus:outline-none focus:ring-2 focus-within:ring-primary py-1 px-2"
            >
                <Autocomplete.Icon
                    className="size-5"
                    render={<IconSearch className="text-tertiary group-focus-within:text-primary" />}
                />
                {searchValue ? null : (
                    <span className="text-tertiary pointer-events-none absolute left-8 top-1/2 -translate-y-1/2 ">
                        <span className="text-tertiary">Search for </span>
                        <span
                            className="transition-opacity duration-200"
                            style={{ opacity: placeholderVisible ? 1 : 0 }}
                        >
                            {placeholderText}
                        </span>
                    </span>
                )}
                <Autocomplete.Input
                    ref={inputRef}
                    value={searchValue}
                    onChange={(e) => handleInputChange(e.target.value)}
                    onKeyDown={handleInputKeyDown}
                    aria-label="Search"
                    id="app-autocomplete-search"
                    className="w-full px-1 py-1 text-sm focus:outline-none border-transparent"
                />

                {showAskAiLink && (
                    <Link
                        className="shrink-0 text-tertiary -mr-1"
                        buttonProps={{
                            size: 'sm',
                            className: 'rounded-sm',
                        }}
                        onClick={handleAskAiLinkClick}
                        to={urls.ai(undefined, searchValue || undefined)}
                    >
                        <KeyboardShortcut tab minimal />
                        {searchValue ? 'Ask PostHog' : 'Open PostHog AI'}
                    </Link>
                )}

                <Autocomplete.Clear
                    render={
                        <ButtonPrimitive
                            iconOnly
                            size="sm"
                            onClick={() => setSearchValue('')}
                            aria-label="Clear search"
                            className="-mr-1"
                        >
                            <IconX className="size-4 text-tertiary" />
                        </ButtonPrimitive>
                    }
                />
            </label>
        </div>
    )
}

// ============================================================================
// Search.Status
// ============================================================================

function SearchStatus(): JSX.Element {
    const { isSearching, searchValue, filteredItems } = useSearchContext()

    const statusMessage = useMemo(() => {
        if (isSearching) {
            return (
                <span className="flex items-center gap-2">
                    <Spinner className="size-3" />
                    <span>Searching...</span>
                </span>
            )
        }
        if (searchValue && filteredItems.length === 0) {
            return 'No results found'
        }
        if (filteredItems.length > 0) {
            if (!searchValue.trim()) {
                return 'Recents and apps'
            }
            return `${filteredItems.length} result${filteredItems.length === 1 ? '' : 's'}`
        }
        return 'Type to search...'
    }, [isSearching, searchValue, filteredItems.length])

    return <Autocomplete.Status className="px-3 pt-1 pb-2 text-xs text-muted">{statusMessage}</Autocomplete.Status>
}

// ============================================================================
// Search.Separator
// ============================================================================

export interface SearchSeparatorProps {
    className?: string
}

function SearchSeparator({ className }: SearchSeparatorProps): JSX.Element {
    return <div className={cn('border-b border-primary', className)} />
}

// ============================================================================
// Search.Results
// ============================================================================

function SearchResults({
    className,
    listClassName,
    groupLabelClassName,
}: {
    className?: string
    listClassName?: string
    groupLabelClassName?: string
}): JSX.Element {
    const { groupedItems, handleItemClick, highlightedItemRef, isSearching } = useSearchContext()

    // Don't show "no results" while any category is still loading
    const isAnyLoading = groupedItems.some((g) => g.isLoading)

    return (
        <ScrollableShadows direction="vertical" styledScrollbars className={cn('flex-1 overflow-y-auto', className)}>
            {!isAnyLoading && (
                <Autocomplete.Empty className="px-3 py-8 text-center text-muted empty:p-0">
                    <span>No results found. Try a different search term.</span>
                </Autocomplete.Empty>
            )}

            <Autocomplete.List className={cn('pt-3 pb-1', listClassName)} tabIndex={-1}>
                {groupedItems.map((group) => {
                    return (
                        <Autocomplete.Group key={group.category} items={group.items} className="mb-4">
                            <Autocomplete.GroupLabel
                                render={
                                    <Label className={cn('px-3 sticky top-0 z-1', groupLabelClassName)} intent="menu">
                                        {getCategoryDisplayName(group.category)}
                                    </Label>
                                }
                            />
                            {group.isLoading && !isSearching ? (
                                <>
                                    {Array.from({
                                        length: group.category === 'recents' ? RECENTS_LIMIT : 10,
                                    }).map((_, i) => (
                                        <div key={i} className="px-1">
                                            <WrappingLoadingSkeleton fullWidth>
                                                <ButtonPrimitive fullWidth className="invisible">
                                                    &nbsp;
                                                </ButtonPrimitive>
                                            </WrappingLoadingSkeleton>
                                        </div>
                                    ))}
                                </>
                            ) : (
                                <Autocomplete.Collection>
                                    {(item: SearchItem) => {
                                        const typeLabel = getItemTypeDisplayName(item.itemType)
                                        const icon = getIconForItem(item)

                                        return (
                                            <ContextMenu key={item.id}>
                                                <ContextMenuTrigger asChild>
                                                    <Autocomplete.Item
                                                        value={item}
                                                        onClick={(e) => {
                                                            e.preventDefault()
                                                            handleItemClick(item)
                                                        }}
                                                        render={(props) => {
                                                            const isHighlighted =
                                                                (props as Record<string, unknown>)[
                                                                    'data-highlighted'
                                                                ] === ''
                                                            if (isHighlighted) {
                                                                highlightedItemRef.current = item
                                                            }
                                                            return (
                                                                <div className="px-1">
                                                                    <Link
                                                                        to={item.href}
                                                                        buttonProps={{
                                                                            fullWidth: true,
                                                                        }}
                                                                        {...props}
                                                                        tabIndex={-1}
                                                                    >
                                                                        {icon}
                                                                        <span className="truncate">
                                                                            {item.displayName || item.name}
                                                                        </span>
                                                                        {(group.category === 'recents' ||
                                                                            group.category === 'groups') &&
                                                                            (item.groupNoun || typeLabel) && (
                                                                                <span className="text-xs text-tertiary shrink-0 mt-[2px]">
                                                                                    {capitalizeFirstLetter(
                                                                                        item.groupNoun ||
                                                                                            typeLabel ||
                                                                                            ''
                                                                                    )}
                                                                                </span>
                                                                            )}
                                                                        {item.productCategory && (
                                                                            <span className="text-xs text-tertiary shrink-0 mt-[2px]">
                                                                                {item.productCategory}
                                                                            </span>
                                                                        )}
                                                                        {item.tags?.map((tag) => (
                                                                            <LemonTag
                                                                                key={tag}
                                                                                type={
                                                                                    tag === 'alpha'
                                                                                        ? 'completion'
                                                                                        : tag === 'beta'
                                                                                          ? 'warning'
                                                                                          : 'success'
                                                                                }
                                                                                size="small"
                                                                                className="shrink-0"
                                                                            >
                                                                                {tag.toUpperCase()}
                                                                            </LemonTag>
                                                                        ))}
                                                                        {item.lastViewedAt && (
                                                                            <span className="ml-auto text-xs text-tertiary whitespace-nowrap shrink-0 mt-[2px]">
                                                                                {formatRelativeTimeShort(
                                                                                    item.lastViewedAt
                                                                                )}
                                                                            </span>
                                                                        )}
                                                                    </Link>
                                                                </div>
                                                            )
                                                        }}
                                                    />
                                                </ContextMenuTrigger>
                                                <ContextMenuContent loop className="max-w-[250px] z-top">
                                                    <ContextMenuGroup>
                                                        <MenuItems
                                                            item={commandItemToTreeDataItem(item)}
                                                            type="context"
                                                            root="project://"
                                                            onlyTree={false}
                                                            showSelectMenuOption={false}
                                                        />
                                                    </ContextMenuGroup>
                                                </ContextMenuContent>
                                            </ContextMenu>
                                        )
                                    }}
                                </Autocomplete.Collection>
                            )}
                        </Autocomplete.Group>
                    )
                })}
            </Autocomplete.List>
        </ScrollableShadows>
    )
}

// ============================================================================
// Search.Footer
// ============================================================================

export interface SearchFooterProps {
    children?: ReactNode
}

function SearchFooter({ children }: SearchFooterProps): JSX.Element {
    const { filteredItems } = useSearchContext()

    return (
        <div className="border-t px-2 py-1 text-xxs text-tertiary font-medium select-none flex items-center gap-1">
            {children ?? (
                <>
                    {filteredItems.length > 1 && (
                        <span>
                            <KeyboardShortcut arrowup arrowdown preserveOrder /> to navigate
                        </span>
                    )}
                    <span>
                        <KeyboardShortcut enter /> to activate
                    </span>
                    <span>
                        <KeyboardShortcut shift enter /> to open in new tab
                    </span>
                    <span>
                        <KeyboardShortcut tab /> to ask AI
                    </span>
                    <span>
                        <KeyboardShortcut escape /> to close
                    </span>
                </>
            )}
        </div>
    )
}

// ============================================================================
// Compound Component Export
// ============================================================================

export const Search = {
    Root: SearchRoot,
    Input: SearchInput,
    Status: SearchStatus,
    Separator: SearchSeparator,
    Results: SearchResults,
    Footer: SearchFooter,
}
