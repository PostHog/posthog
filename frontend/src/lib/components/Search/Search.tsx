import { Autocomplete } from '@base-ui/react/autocomplete'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { router } from 'kea-router'
import {
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
import { Link, Spinner } from '@posthog/lemon-ui'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuGroup, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { ProductIconWrapper, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { SearchItem, searchLogic } from './searchLogic'
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
    const typeDisplayNames: Record<string, string> = {
        dashboard: 'Dashboard',
        insight: 'Insight',
        'insight/funnels': 'Funnel',
        'insight/trends': 'Trend',
        'insight/retention': 'Retention',
        'insight/paths': 'Paths',
        'insight/lifecycle': 'Lifecycle',
        'insight/stickiness': 'Stickiness',
        'insight/hog': 'SQL insight',
        query: 'SQL query',
        product_analytics: 'Product analytics',
        web_analytics: 'Web analytics',
        llm_analytics: 'LLM analytics',
        revenue_analytics: 'Revenue analytics',
        marketing_analytics: 'Marketing analytics',
        session_replay: 'Session replay',
        session_recording_playlist: 'Session recording filter',
        error_tracking: 'Error tracking',
        feature_flag: 'Feature flag',
        experiment: 'Experiment',
        early_access_feature: 'Early access feature',
        survey: 'Survey',
        product_tour: 'Product tour',
        user_interview: 'User interview',
        notebook: 'Notebook',
        cohort: 'Cohort',
        action: 'Action',
        annotation: 'Annotation',
        event_definition: 'Event',
        property_definition: 'Property',
        data_warehouse: 'Data warehouse',
        data_pipeline: 'Data pipeline',
        persons: 'Person',
        user: 'User',
        group: 'Group',
        heatmap: 'Heatmap',
        link: 'Link',
        workflows: 'Workflow',
        sql_editor: 'SQL query',
        logs: 'Logs',
        alert: 'Alert',
        folder: 'Folder',
    }
    return typeDisplayNames[type] || null
}

const getIconForItem = (item: SearchItem): ReactNode => {
    if (item.icon) {
        return item.icon
    }
    const itemType = item.itemType || item.record?.type
    if (itemType) {
        return (
            <ProductIconWrapper type={itemType as string}>
                {iconForType(itemType as FileSystemIconType)}
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
    groupedItems: { category: string; items: SearchItem[] }[]
    isSearching: boolean
    isActive: boolean
    inputRef: RefObject<HTMLInputElement>
    handleItemClick: (item: SearchItem) => void
    showAskAiLink: boolean
    onAskAiClick?: () => void
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
    isActive = true,
    onItemSelect,
    showAskAiLink = true,
    onAskAiClick,
    className = '',
}: SearchRootProps): JSX.Element {
    const { allCategories, isSearching } = useValues(searchLogic)
    const { setSearch } = useActions(searchLogic)

    const [searchValue, setSearchValue] = useState('')
    const [filteredItems, setFilteredItems] = useState<SearchItem[]>([])
    const inputRef = useRef<HTMLInputElement>(null!)
    const actionsRef = useRef<Autocomplete.Root.Actions>(null)

    const allItems = useMemo(() => {
        const items: SearchItem[] = []
        for (const category of allCategories) {
            items.push(...category.items)
        }
        return items
    }, [allCategories])

    useEffect(() => {
        if (!isActive) {
            return
        }
        setSearch(searchValue)
    }, [searchValue, setSearch, isActive])

    useEffect(() => {
        if (searchValue.trim()) {
            const searchLower = searchValue.toLowerCase()
            setFilteredItems(
                allItems.filter((item) => {
                    if (item.category === 'recents') {
                        const name = (item.displayName || item.name || '').toLowerCase()
                        return name.includes(searchLower)
                    }
                    return true
                })
            )
        } else {
            setFilteredItems(allItems.filter((item) => item.category === 'recents'))
        }
    }, [allItems, searchValue])

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
        const groups: { category: string; items: SearchItem[] }[] = []
        const categoryMap = new Map<string, SearchItem[]>()

        for (const item of filteredItems) {
            const existing = categoryMap.get(item.category)
            if (existing) {
                existing.push(item)
            } else {
                categoryMap.set(item.category, [item])
            }
        }

        for (const [category, items] of categoryMap) {
            groups.push({ category, items })
        }

        return groups
    }, [filteredItems])

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
        }),
        [searchValue, filteredItems, groupedItems, isSearching, isActive, handleItemClick, showAskAiLink, onAskAiClick]
    )

    return (
        <SearchContext.Provider value={contextValue}>
            <div className={`flex flex-col overflow-hidden ${className}`}>
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
    const { searchValue, setSearchValue, isActive, inputRef, showAskAiLink, onAskAiClick } = useSearchContext()

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
                        Ask AI
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
                return 'Recent items'
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
    const { groupedItems, isSearching, handleItemClick } = useSearchContext()

    return (
        <ScrollableShadows direction="vertical" styledScrollbars className={cn('flex-1 overflow-y-auto', className)}>
            <Autocomplete.Empty className="px-3 py-8 text-center text-muted empty:p-0">
                {isSearching ? (
                    <div className="flex flex-col items-center gap-2">
                        <Spinner className="size-5" />
                        <span>Searching...</span>
                    </div>
                ) : (
                    <span>No results found. Try a different search term.</span>
                )}
            </Autocomplete.Empty>

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
                            <Autocomplete.Collection>
                                {(item: SearchItem) => {
                                    const typeLabel = getItemTypeDisplayName(item.itemType)
                                    const icon = getIconForItem(item)

                                    return (
                                        <ContextMenu key={item.id}>
                                            <ContextMenuTrigger asChild>
                                                <Autocomplete.Item
                                                    value={item}
                                                    onClick={() => handleItemClick(item)}
                                                    render={(props) => (
                                                        <div className="px-1">
                                                            <ButtonPrimitive
                                                                fullWidth
                                                                onClick={() => handleItemClick(item)}
                                                                {...props}
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
                                                                                item.groupNoun || typeLabel || ''
                                                                            )}
                                                                        </span>
                                                                    )}
                                                                {item.lastViewedAt && (
                                                                    <span className="ml-auto text-xs text-tertiary whitespace-nowrap shrink-0 mt-[2px]">
                                                                        {formatRelativeTimeShort(item.lastViewedAt)}
                                                                    </span>
                                                                )}
                                                            </ButtonPrimitive>
                                                        </div>
                                                    )}
                                                />
                                            </ContextMenuTrigger>
                                            <ContextMenuContent loop className="max-w-[250px]">
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
                            <KeyboardShortcut arrowup arrowdown preserveOrder /> to navigate •{' '}
                        </span>
                    )}
                    <span>
                        <KeyboardShortcut enter /> to activate
                    </span>
                    <span>
                        <KeyboardShortcut shift enter /> to open in new tab
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
