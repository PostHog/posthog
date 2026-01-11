import { Autocomplete } from '@base-ui/react/autocomplete'
import { Dialog } from '@base-ui/react/dialog'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { router } from 'kea-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconSearch, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuGroup, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import { Label } from 'lib/ui/Label/Label'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { ProductIconWrapper, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { commandLogic } from './commandLogic'
import { CommandSearchItem, commandSearchLogic } from './commandSearchLogic'

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

const useRotatingPlaceholder = (isActive: boolean): { text: string; isVisible: boolean } => {
    const [index, setIndex] = useState(0)
    const [isVisible, setIsVisible] = useState(true)

    useEffect(() => {
        if (!isActive) {
            setIndex(0)
            setIsVisible(true)
            return
        }

        const interval = setInterval(() => {
            setIsVisible(false)
            setTimeout(() => {
                setIndex((prev) => (prev + 1) % PLACEHOLDER_OPTIONS.length)
                setIsVisible(true)
            }, 200) // fade out duration
        }, PLACEHOLDER_CYCLE_INTERVAL)

        return () => clearInterval(interval)
    }, [isActive])

    return { text: PLACEHOLDER_OPTIONS[index], isVisible }
}

const getItemTypeDisplayName = (type: string | null | undefined): string | null => {
    if (!type) {
        return null
    }
    const typeDisplayNames: Record<string, string> = {
        // Dashboards & Insights
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

        // Analytics products
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

        // Data
        notebook: 'Notebook',
        cohort: 'Cohort',
        action: 'Action',
        annotation: 'Annotation',
        event_definition: 'Event',
        property_definition: 'Property',
        data_warehouse: 'Data warehouse',
        data_pipeline: 'Data pipeline',

        // People
        persons: 'Person',
        user: 'User',
        group: 'Group',

        // Other
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

const getCategoryDisplayName = (category: string): string => {
    const displayNames: Record<string, string> = {
        // Category names
        recents: 'Recents',
        insight: 'Insights',
        dashboard: 'Dashboards',
        feature_flag: 'Feature flags',
        experiment: 'Experiments',
        survey: 'Surveys',
        notebook: 'Notebooks',
        cohort: 'Cohorts',
        action: 'Actions',
        session_recording_playlist: 'Session recording filter',
        persons: 'Persons',
        groups: 'Groups',
    }
    return displayNames[category] || category
}

const formatRelativeTimeShort = (dateString: string): string => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) {
        return 'now'
    }
    if (diffMins < 60) {
        return `${diffMins}m`
    }
    if (diffHours < 24) {
        return `${diffHours}h`
    }
    if (diffDays < 7) {
        return `${diffDays}d`
    }
    if (diffDays < 30) {
        return `${Math.floor(diffDays / 7)}w`
    }
    return `${Math.floor(diffDays / 30)}mo`
}

const getIconForItem = (item: CommandSearchItem): React.ReactNode => {
    if (item.icon) {
        return item.icon
    }
    // Use the iconForType helper for file system items
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

const commandItemToTreeDataItem = (item: CommandSearchItem): TreeDataItem => {
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

export function Command(): JSX.Element {
    const { isCommandOpen } = useValues(commandLogic)
    const { closeCommand } = useActions(commandLogic)

    const { allCategories, isSearching } = useValues(commandSearchLogic)
    const { setSearch } = useActions(commandSearchLogic)

    const [searchValue, setSearchValue] = useState('')
    const [filteredItems, setFilteredItems] = useState<CommandSearchItem[]>([])
    const inputRef = useRef<HTMLInputElement>(null)
    const actionsRef = useRef<Autocomplete.Root.Actions>(null)

    const { text: placeholderText, isVisible: placeholderVisible } = useRotatingPlaceholder(
        isCommandOpen && !searchValue
    )

    const { contains } = Autocomplete.useFilter({ sensitivity: 'base' })

    // Flatten all category items into a single list
    const allItems = useMemo(() => {
        const items: CommandSearchItem[] = []
        for (const category of allCategories) {
            items.push(...category.items)
        }
        return items
    }, [allCategories])

    // Debounced search effect
    useEffect(() => {
        if (!isCommandOpen) {
            return
        }

        const timeoutId = setTimeout(() => {
            setSearch(searchValue)
        }, 150)

        return () => {
            clearTimeout(timeoutId)
        }
    }, [searchValue, setSearch, isCommandOpen])

    // Update filtered items when allItems or search changes
    // No search = show recents only, with search = search all categories
    useEffect(() => {
        let filtered = allItems

        if (searchValue.trim()) {
            // When searching, search across all categories
            filtered = filtered.filter((item) => contains(item.name, searchValue))
        } else {
            // No search term - show only recents
            filtered = filtered.filter((item) => item.category === 'recents')
        }

        setFilteredItems(filtered)
    }, [allItems, searchValue, contains])

    // Focus input when dialog opens
    useEffect(() => {
        if (isCommandOpen && inputRef.current) {
            setTimeout(() => {
                inputRef.current?.focus()
            }, 50)
        }
    }, [isCommandOpen])

    // Reset search when dialog closes
    useEffect(() => {
        if (!isCommandOpen) {
            setSearchValue('')
            setSearch('')
        }
    }, [isCommandOpen, setSearch])

    const handleItemClick = useCallback(
        (item: CommandSearchItem) => {
            if (item.href) {
                router.actions.push(item.href)
                closeCommand()
            }
        },
        [closeCommand]
    )

    const handleInputChange = useCallback((value: string) => {
        setSearchValue(value)
    }, [])

    // Group items by category for rendering
    const groupedItems = useMemo(() => {
        const groups: { category: string; items: CommandSearchItem[] }[] = []
        const categoryMap = new Map<string, CommandSearchItem[]>()

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

    // Build status message
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

    return (
        <Dialog.Root open={isCommandOpen} onOpenChange={(open) => !open && closeCommand()}>
            <Dialog.Portal>
                <Dialog.Backdrop className="fixed inset-0 min-h-screen min-w-screen bg-black opacity-20 transition-all duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 dark:opacity-70" />
                <Dialog.Popup className="fixed top-1/4 left-1/2 w-[640px] max-w-[calc(100vw-3rem)] max-h-[60vh] -translate-x-1/2 rounded-lg bg-surface-secondary shadow-xl border border-primary transition-all duration-150 data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0 flex flex-col overflow-hidden">
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
                        <div className="p-1 space-y-2">
                            <label
                                htmlFor="command-palette-search"
                                className="group input-like flex gap-1 items-center relative w-full bg-fill-input border border-primary focus:outline-none focus:ring-2 focus-within:ring-primary py-1 px-2"
                            >
                                <Autocomplete.Icon
                                    className="size-4"
                                    render={<IconSearch className="text-tertiary group-focus-within:text-primary" />}
                                />
                                {searchValue ? null : (
                                    <span className="text-tertiary pointer-events-none absolute left-8 top-1/2 -translate-y-1/2 ">
                                        Search for{' '}
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
                                    aria-label="Command palette search"
                                    id="command-palette-search"
                                    className="w-full px-1 py-1 text-sm focus:outline-none border-transparent"
                                />
                                <span className="pointer-events-none whitespace-nowrap">
                                    <KeyboardShortcut command k minimal />
                                </span>
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

                        <ScrollableShadows direction="vertical" styledScrollbars className="flex-1 overflow-y-auto">
                            <Autocomplete.Status className="px-3 pt-1 pb-2 text-xs text-muted border-b border-primary">
                                {statusMessage}
                            </Autocomplete.Status>

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

                            <Autocomplete.List className="pt-3 pb-1">
                                {groupedItems.map((group) => {
                                    return (
                                        <Autocomplete.Group key={group.category} items={group.items} className="mb-4">
                                            <Autocomplete.GroupLabel
                                                render={
                                                    <Label
                                                        className="px-3 sticky top-0 bg-surface-secondary"
                                                        intent="menu"
                                                    >
                                                        {getCategoryDisplayName(group.category)}
                                                    </Label>
                                                }
                                            />
                                            <Autocomplete.Collection>
                                                {(item: CommandSearchItem) => {
                                                    const typeLabel = getItemTypeDisplayName(item.itemType)
                                                    const icon = getIconForItem(item)

                                                    return (
                                                        <ContextMenu key={item.id}>
                                                            <ContextMenuTrigger asChild>
                                                                <Autocomplete.Item
                                                                    value={item}
                                                                    onClick={() => handleItemClick(item)}
                                                                    className="flex items-center gap-2 px-3 py-2 mx-1 rounded cursor-pointer text-sm text-primary hover:bg-fill-highlight-100 data-[highlighted]:bg-fill-highlight-100 data-[highlighted]:outline-none transition-colors"
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
                                                                </Autocomplete.Item>
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

                        <div className="border-t px-2 py-1 text-xxs text-tertiary font-medium select-none">
                            {filteredItems.length > 1 && <span>↑↓ to navigate • </span>}
                            <span>⏎ to activate • Esc to close</span>
                        </div>
                    </Autocomplete.Root>
                </Dialog.Popup>
            </Dialog.Portal>
        </Dialog.Root>
    )
}
