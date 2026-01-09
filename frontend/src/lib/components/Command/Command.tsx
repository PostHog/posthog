import { Autocomplete } from '@base-ui/react/autocomplete'
import { Dialog } from '@base-ui/react/dialog'
import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'

import { IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { NewTabTreeDataItem, getNewTabProjectTreeLogicProps, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { commandLogic } from './commandLogic'

interface CommandItem {
    id: string
    name: string
    category: string
    href?: string
    icon?: React.ReactNode
}

type CategoryFilter =
    | 'all'
    | 'create-new'
    | 'apps'
    | 'data-management'
    | 'recents'
    | 'persons'
    | 'groups'
    | 'eventDefinitions'
    | 'propertyDefinitions'
    | 'askAI'

const CATEGORY_FILTERS: { value: CategoryFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'recents', label: 'Recents' },
    { value: 'create-new', label: 'Create' },
    { value: 'apps', label: 'Apps' },
    { value: 'persons', label: 'Persons' },
    { value: 'askAI', label: 'AI' },
]

const mapToCommandItems = (items: NewTabTreeDataItem[]): CommandItem[] => {
    return items.map((item) => ({
        id: item.id,
        name: item.name,
        category: item.category,
        href: item.href,
        icon: item.icon,
    }))
}

export function Command(): JSX.Element {
    const { isCommandOpen } = useValues(commandLogic)
    const { closeCommand } = useActions(commandLogic)

    const tabId = 'command-palette'
    const projectTreeLogicProps = useMemo(() => getNewTabProjectTreeLogicProps(tabId), [])
    useMountedLogic(projectTreeLogic(projectTreeLogicProps))

    const { allCategories, isSearching } = useValues(newTabSceneLogic({ tabId }))
    const { setSearch } = useActions(newTabSceneLogic({ tabId }))

    const [searchValue, setSearchValue] = useState('')
    const [filteredItems, setFilteredItems] = useState<CommandItem[]>([])
    const [selectedCategory, setSelectedCategory] = useState<CategoryFilter>('all')
    const inputRef = useRef<HTMLInputElement>(null)
    const actionsRef = useRef<Autocomplete.Root.Actions>(null)

    const { contains } = Autocomplete.useFilter({ sensitivity: 'base' })

    // Flatten all category items into a single list
    const allItems = useMemo(() => {
        const items: CommandItem[] = []
        for (const category of allCategories) {
            items.push(...mapToCommandItems(category.items))
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

    // Update filtered items when allItems, search, or category changes
    useEffect(() => {
        let filtered = allItems

        // Filter by category if not 'all'
        if (selectedCategory !== 'all') {
            filtered = filtered.filter((item) => item.category === selectedCategory)
        }

        // Filter by search term
        if (searchValue.trim()) {
            filtered = filtered.filter((item) => contains(item.name, searchValue))
        }

        setFilteredItems(filtered)
    }, [allItems, searchValue, selectedCategory, contains])

    // Focus input when dialog opens
    useEffect(() => {
        if (isCommandOpen && inputRef.current) {
            setTimeout(() => {
                inputRef.current?.focus()
            }, 50)
        }
    }, [isCommandOpen])

    // Reset search and category when dialog closes
    useEffect(() => {
        if (!isCommandOpen) {
            setSearchValue('')
            setSearch('')
            setSelectedCategory('all')
        }
    }, [isCommandOpen, setSearch])

    const handleItemClick = useCallback(
        (item: CommandItem) => {
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

    const handleCategorySelect = useCallback((category: CategoryFilter) => {
        setSelectedCategory(category)
        inputRef.current?.focus()
    }, [])

    const handleCategoryKeyDown = useCallback(
        (e: ReactKeyboardEvent<HTMLButtonElement>, category: CategoryFilter) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                handleCategorySelect(category)
            }
        },
        [handleCategorySelect]
    )

    // Group items by category for rendering
    const groupedItems = useMemo(() => {
        const groups: { category: string; items: CommandItem[] }[] = []
        const categoryMap = new Map<string, CommandItem[]>()

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

    const getCategoryDisplayName = (category: string): string => {
        const displayNames: Record<string, string> = {
            'create-new': 'Create new',
            apps: 'Apps',
            'data-management': 'Data management',
            recents: 'Recents',
            folders: 'Folders',
            persons: 'Persons',
            groups: 'Groups',
            eventDefinitions: 'Events',
            propertyDefinitions: 'Properties',
            askAI: 'Posthog AI',
        }
        return displayNames[category] || category
    }

    // Build status message
    const statusMessage = useMemo(() => {
        const categoryLabel =
            selectedCategory !== 'all' ? CATEGORY_FILTERS.find((f) => f.value === selectedCategory)?.label : null

        if (isSearching) {
            return (
                <span className="flex items-center gap-2">
                    <Spinner className="size-3" />
                    <span>Searching{categoryLabel ? ` in ${categoryLabel}` : ''}...</span>
                </span>
            )
        }
        if ((searchValue || selectedCategory !== 'all') && filteredItems.length === 0) {
            return `No results found${categoryLabel ? ` in ${categoryLabel}` : ''}`
        }
        if (filteredItems.length > 0) {
            const suffix = categoryLabel ? ` in ${categoryLabel}` : ''
            return `${filteredItems.length} result${filteredItems.length === 1 ? '' : 's'}${suffix}`
        }
        return 'Type to search...'
    }, [isSearching, searchValue, filteredItems.length, selectedCategory])

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
                        <div className="p-2 border-b border-primary space-y-2 bg-surface-primary">
                            <div className="input-like relative">
                                <Autocomplete.Input
                                    ref={inputRef}
                                    value={searchValue}
                                    onChange={(e) => handleInputChange(e.target.value)}
                                    placeholder="Search or ask an AI question..."
                                    className="w-full px-3 py-2 text-sm bg-fill-input border border-primary rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent placeholder:text-muted"
                                    aria-label="Command palette search"
                                />
                                <Autocomplete.Clear
                                    className="absolute right-1 top-1/2 -translate-y-1/2"
                                    render={
                                        <ButtonPrimitive
                                            iconOnly
                                            size="sm"
                                            onClick={() => setSearchValue('')}
                                            aria-label="Clear search"
                                        >
                                            <IconX className="size-4 text-tertiary" />
                                        </ButtonPrimitive>
                                    }
                                />
                            </div>
                            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by category">
                                {CATEGORY_FILTERS.map((filter) => (
                                    <ButtonPrimitive
                                        key={filter.value}
                                        type="button"
                                        role="tab"
                                        size="sm"
                                        aria-selected={selectedCategory === filter.value}
                                        tabIndex={0}
                                        aria-label={`Filter by ${filter.label}`}
                                        onClick={() => handleCategorySelect(filter.value)}
                                        onKeyDown={(e) => handleCategoryKeyDown(e, filter.value)}
                                        className={clsx(
                                            'px-2',
                                            selectedCategory === filter.value
                                                ? 'bg-fill-highlight-100 text-primary'
                                                : 'text-muted hover:text-primary hover:bg-fill-highlight-50'
                                        )}
                                    >
                                        {filter.label}
                                    </ButtonPrimitive>
                                ))}
                            </div>
                        </div>

                        <ScrollableShadows direction="vertical" styledScrollbars className="flex-1 overflow-y-auto">
                            <Autocomplete.Status className="px-3 py-2 text-xs text-muted border-b border-primary">
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
                                {groupedItems.map((group) => (
                                    <Autocomplete.Group key={group.category} items={group.items} className="mb-4">
                                        {selectedCategory === 'all' && (
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
                                        )}
                                        <Autocomplete.Collection>
                                            {(item: CommandItem) => (
                                                <Autocomplete.Item
                                                    key={item.id}
                                                    value={item}
                                                    onClick={() => handleItemClick(item)}
                                                    className="flex items-center gap-2 px-3 py-2 mx-1 rounded cursor-pointer text-sm text-primary hover:bg-fill-highlight-100 data-[highlighted]:bg-fill-highlight-100 data-[highlighted]:outline-none transition-colors"
                                                >
                                                    {item.icon && item.icon}
                                                    <span className="truncate">{item.name}</span>
                                                </Autocomplete.Item>
                                            )}
                                        </Autocomplete.Collection>
                                    </Autocomplete.Group>
                                ))}
                            </Autocomplete.List>
                        </ScrollableShadows>

                        <div className="border-t px-2 py-1 text-xxs text-tertiary font-medium select-none">
                            {filteredItems.length > 1 && <span>↑↓ to navigate • </span>}
                            <span>⏎ to activate • → to select • Esc to close</span>
                        </div>
                    </Autocomplete.Root>
                </Dialog.Popup>
            </Dialog.Portal>
        </Dialog.Root>
    )
}
