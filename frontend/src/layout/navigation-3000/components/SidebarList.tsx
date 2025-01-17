import { DndContext, DragEndEvent, DragOverlay, MouseSensor, TouchSensor, useSensor, useSensors } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Link, TZLabel } from '@posthog/apps-common'
import { IconCheckCircle, IconEllipsis, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, lemonToast } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import clsx from 'clsx'
import { useActions, useAsyncActions, useValues } from 'kea'
import { isDayjs } from 'lib/dayjs'
import { IconChevronRight } from 'lib/lemon-ui/icons/icons'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { capitalizeFirstLetter } from 'lib/utils'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { InfiniteLoader } from 'react-virtualized/dist/es/InfiniteLoader'
import { List, ListProps } from 'react-virtualized/dist/es/List'

import { editorSidebarLogic } from '~/scenes/data-warehouse/editor/editorSidebarLogic'

import { ITEM_KEY_PART_SEPARATOR, navigation3000Logic } from '../navigationLogic'
import {
    BasicListItem,
    ButtonListItem,
    ExtendedListItem,
    ExtraListItemContext,
    ListItemAccordion,
    SidebarCategory,
    SidebarCategoryBase,
    TentativeListItem,
} from '../types'
import { KeyboardShortcut } from './KeyboardShortcut'
import { pluralizeCategory } from './SidebarAccordion'

const isListItemAccordion = (
    category: BasicListItem | ExtendedListItem | TentativeListItem | ButtonListItem | ListItemAccordion
): category is ListItemAccordion => {
    return 'items' in category
}

const isSidebarCategory = (category: SidebarCategory | SidebarCategoryBase): category is SidebarCategory => {
    return 'loading' in category
}

export function SidebarList({ category }: { category: SidebarCategory | ListItemAccordion }): JSX.Element {
    const listRef = useRef<List | null>(null)
    const {
        isListItemVisible,
        listItemAccordionCollapseMapping,
        normalizedActiveListItemKey,
        sidebarWidth,
        newItemInlineCategory,
        savingNewItem,
    } = useValues(navigation3000Logic)
    const { cancelNewItem } = useActions(navigation3000Logic)
    const { saveNewItem } = useAsyncActions(navigation3000Logic)
    const { folders, isFolder } = useValues(editorSidebarLogic)
    const { moveViewToFolder } = useActions(editorSidebarLogic)
    const [activeId, setActiveId] = useState<string | null>(null)

    const sensors = useSensors(
        useSensor(MouseSensor, {
            activationConstraint: {
                delay: 100,
                tolerance: 5,
            },
        }),
        useSensor(TouchSensor, {
            activationConstraint: {
                delay: 100,
                tolerance: 5,
            },
        })
    )

    const handleDragEnd = (event: DragEndEvent): void => {
        const { active, over } = event

        // Get the last item in the chain of item separator
        const getLastItemInChain = (key: string): string => {
            const parts = key.split(ITEM_KEY_PART_SEPARATOR)
            return parts[parts.length - 1]
        }

        if (over && active.id !== over.id) {
            const activeId = active.id.toString()
            const overId = over.id.toString()

            const overItemKey = getLastItemInChain(overId)
            const activeItemKey = getLastItemInChain(activeId)

            // If dropping onto a folder, move to that folder
            if (isFolder(overItemKey)) {
                moveViewToFolder({ viewId: activeItemKey, toFolderId: overItemKey })
            } else {
                const currentFolder = folders.find((folder) => folder.items.includes(activeItemKey))
                if (currentFolder) {
                    moveViewToFolder({ viewId: activeItemKey, toFolderId: '' }) // Empty string as folderId removes it from folders
                }
            }
        } else {
            const activeId = active.id.toString()
            const activeItemKey = getLastItemInChain(activeId)
            // If dropping outside folders, remove from current folder
            moveViewToFolder({ viewId: activeItemKey, toFolderId: '' })
        }
        setActiveId(null)
    }

    const handleDragStart = (event: DragEndEvent): void => {
        setActiveId(event.active.id.toString())
    }

    const emptyStateSkeletonCount = useMemo(() => 4 + Math.floor(Math.random() * 4), [])

    const { items: _items } = category

    const listItems = useMemo(() => {
        const allItems: (BasicListItem | ExtendedListItem | ListItemAccordion)[] = []

        const flatten = (
            items: (BasicListItem | ExtendedListItem | ListItemAccordion)[],
            depth: number = 1,
            parentKey: string | number | null = null
        ): void => {
            items.forEach((item) => {
                const itemKey = parentKey ? `${parentKey}${ITEM_KEY_PART_SEPARATOR}${item.key}` : item.key.toString()

                allItems.push({
                    ...item,
                    depth: depth,
                    key: itemKey,
                })
                if (isListItemAccordion(item)) {
                    flatten(item.items, depth + 1, itemKey)
                }
            })
        }

        flatten(_items, 1, category.key.toString())

        return allItems.filter((item) => isListItemVisible(item.key.toString()))
    }, [_items, isListItemVisible])

    useEffect(() => {
        if (listRef.current) {
            listRef.current.recomputeRowHeights()
            listRef.current.forceUpdateGrid()
        }
    }, [listItemAccordionCollapseMapping, listItems])

    const remote = isSidebarCategory(category) ? category.remote : undefined
    const loading = isSidebarCategory(category) ? category.loading : false
    const validateName = isSidebarCategory(category) ? category.validateName : undefined

    const addingNewItem = newItemInlineCategory === category.key
    const firstItem = listItems.find(Boolean)
    const usingExtendedItemFormat = !!firstItem && 'summary' in firstItem

    const listProps = {
        className: 'SidebarList',
        width: sidebarWidth,
        rowHeight: usingExtendedItemFormat ? 46 : 32,
        rowRenderer: ({ index: rawIndex, style }) => {
            const index = addingNewItem ? rawIndex - 1 : rawIndex // Adjusted for tentative item
            if (index === -1) {
                return (
                    <SidebarListItem
                        key={index}
                        item={
                            {
                                key: '__tentative__',
                                onSave: async (newName) => saveNewItem(newName),
                                onCancel: cancelNewItem,
                                loading: savingNewItem,
                            } as TentativeListItem
                        }
                        validateName={validateName}
                        style={style}
                    />
                )
            }

            const item = listItems[index]
            if (!item) {
                return <SidebarListItemSkeleton key={index} style={style} />
            }

            const normalizedItemKey = `${category.key}${ITEM_KEY_PART_SEPARATOR}${item.key}`
            const active = normalizedItemKey === normalizedActiveListItemKey

            return <SidebarListItem key={index} item={item} validateName={validateName} active={active} style={style} />
        },
        overscanRowCount: 20,
        tabIndex: null,
    } as ListProps
    return (
        <DndContext sensors={sensors} onDragEnd={handleDragEnd} onDragStart={handleDragStart}>
            <div className="flex-1" aria-busy={loading}>
                <AutoSizer disableWidth>
                    {({ height }) =>
                        'loading' in category && category.items.length === 0 ? (
                            Array(emptyStateSkeletonCount)
                                .fill(null)
                                .map((_, index) => <SidebarListItemSkeleton key={index} style={{ height: 32 }} />)
                        ) : remote ? (
                            <InfiniteLoader
                                isRowLoaded={({ index }) => remote.isItemLoaded(index)}
                                loadMoreRows={({ startIndex, stopIndex }) =>
                                    remote.loadMoreItems(startIndex, stopIndex)
                                }
                                rowCount={remote.itemCount}
                                minimumBatchSize={remote.minimumBatchSize || 100}
                            >
                                {({ onRowsRendered, registerChild }) => (
                                    <List
                                        {...listProps}
                                        ref={registerChild}
                                        height={height}
                                        rowCount={remote.itemCount + Number(addingNewItem)}
                                        onRowsRendered={onRowsRendered}
                                    />
                                )}
                            </InfiniteLoader>
                        ) : (
                            <List
                                ref={listRef}
                                {...listProps}
                                height={height}
                                rowCount={listItems.length + Number(addingNewItem)}
                            />
                        )
                    }
                </AutoSizer>
            </div>
            <DragOverlay>
                {activeId ? (
                    <div className="SidebarListItem SidebarListItem__button SidebarListItem--overlay">
                        {listItems.find((item) => item.key.toString() === activeId)?.name}
                    </div>
                ) : null}
            </DragOverlay>
        </DndContext>
    )
}

interface SidebarListItemProps {
    item: BasicListItem | ExtendedListItem | TentativeListItem | ButtonListItem | ListItemAccordion
    validateName?: SidebarCategory['validateName']
    active?: boolean
    style: React.CSSProperties
}

function isItemTentative(item: SidebarListItemProps['item']): item is TentativeListItem {
    return 'onSave' in item
}

function isItemClickable(item: SidebarListItemProps['item']): item is ButtonListItem {
    return 'onClick' in item
}

function SidebarListItem({ item, validateName, active, style: styleFromProps }: SidebarListItemProps): JSX.Element {
    const [isMenuOpen, setIsMenuOpen] = useState(false)
    const [newName, setNewName] = useState<null | string>(null)
    const [newNameValidationError, setNewNameValidationError] = useState<null | string>(null)
    const [isSavingName, setIsSavingName] = useState(false)
    const [menuItemsVisible, setMenuItemsVisible] = useState(true)

    const ref = useRef<HTMLElement | null>(null)
    item.ref = ref // Inject ref for keyboard navigation

    const isSaving = isItemTentative(item) ? item.loading : isSavingName

    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: item.key.toString(),
        disabled: isItemTentative(item) || isListItemAccordion(item) || newName !== null,
    })

    const combinedStyle = {
        ...styleFromProps,
        transform: CSS.Transform.toString(transform),
        transition,
    }

    const menuItems = useMemo(() => {
        if (isItemTentative(item)) {
            return undefined
        }
        if (item.onRename && !isListItemAccordion(item)) {
            if (typeof item.menuItems !== 'function') {
                throw new Error('menuItems must be a function for renamable items so that the "Rename" item is shown')
            }
            return item.menuItems(() => setNewName(item.name))
        }
        return typeof item.menuItems === 'function'
            ? item.menuItems(() => console.error('Cannot rename item without onRename handler'))
            : item.menuItems
    }, [item, setNewName])

    const cancel = (): void => {
        if (isItemTentative(item)) {
            item.onCancel()
        }
        setNewName(null)
        setNewNameValidationError(null)
    }
    const validate = (name: string): boolean => {
        if (validateName) {
            const validation = validateName(name)
            setNewNameValidationError(validation || null)
            return !validation
        }
        return true
    }
    const save = useMemo(
        () =>
            isItemTentative(item)
                ? async (name: string): Promise<void> => {
                      if (!validate(name)) {
                          return
                      }
                      await item.onSave(name)
                  }
                : !isListItemAccordion(item) && item.onRename
                ? async (newName: string): Promise<void> => {
                      if (!newName || newName === item.name) {
                          return cancel() // No change to be saved
                      }
                      if (!validate(newName)) {
                          return
                      }
                      setIsSavingName(true)
                      try {
                          await item.onRename?.(newName)
                      } catch (error) {
                          captureException(error)
                          lemonToast.error('Could not rename item')
                      } finally {
                          setIsSavingName(false)
                          cancel()
                      }
                  }
                : null,
        [item, validate, cancel]
    )

    useEffect(() => {
        // Add double-click handler for renaming
        if (!isItemTentative(item) && !isListItemAccordion(item) && save && newName === null) {
            const onDoubleClick = (): void => {
                setNewName(item.name)
            }
            const element = ref.current
            if (element) {
                element.addEventListener('dblclick', onDoubleClick)
                return () => {
                    element.removeEventListener('dblclick', onDoubleClick)
                }
            }
        }
    }, [item, save, newName])

    let content: JSX.Element
    if (isListItemAccordion(item)) {
        content = (
            <SidebarListItemAccordion category={item} onEditing={(isEditing) => setMenuItemsVisible(!isEditing)} />
        )
    } else if (isItemClickable(item)) {
        content = (
            <li
                className="SidebarListItem__button"
                onClick={item.onClick}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--depth': item.depth } as React.CSSProperties}
            >
                {item.icon && <div className="SidebarListItem__icon">{item.icon}</div>}
                <h5 className="SidebarListItem__name">{item.name}</h5>
            </li>
        )
    } else if (!save || (!isItemTentative(item) && newName === null)) {
        if (isItemTentative(item)) {
            throw new Error('Tentative items should not be rendered in read mode')
        }
        let formattedName = item.searchMatch?.nameHighlightRanges?.length ? (
            <TextWithHighlights ranges={item.searchMatch.nameHighlightRanges}>{item.name}</TextWithHighlights>
        ) : (
            item.name
        )
        if (!item.url || item.isNamePlaceholder) {
            formattedName = <i>{formattedName}</i>
        }
        if (item.tag) {
            formattedName = (
                <>
                    {formattedName}
                    <LemonTag type={item.tag.status} size="small" className="ml-2">
                        {item.tag.text}
                    </LemonTag>
                </>
            )
        }
        content = (
            <Link
                ref={ref as React.RefObject<HTMLAnchorElement>}
                to={item.url || undefined}
                className="SidebarListItem__link"
                onKeyDown={(e) => {
                    if (e.key === 'ArrowDown') {
                        if (e.metaKey || e.ctrlKey) {
                            ;(e.target as HTMLElement).click()
                        } else {
                            navigation3000Logic.actions.focusNextItem()
                            e.preventDefault()
                        }
                    } else if (e.key === 'ArrowUp') {
                        navigation3000Logic.actions.focusPreviousItem()
                        e.preventDefault()
                    } else if (save && e.key === 'Enter') {
                        setNewName(item.name)
                        e.preventDefault()
                    }
                }}
                onFocus={() => {
                    navigation3000Logic.actions.setLastFocusedItemByKey(
                        Array.isArray(item.key) ? item.key[0] : item.key
                    )
                }}
            >
                {'summary' in item ? (
                    <>
                        <div className="flex space-between gap-1">
                            <h5 className="flex-1">{formattedName}</h5>
                            <div>
                                <ExtraContext data={item.extraContextTop} />
                            </div>
                        </div>
                        <div className="flex space-between gap-1">
                            <div className="flex-1 overflow-hidden text-ellipsis">
                                {item.searchMatch?.matchingFields
                                    ? `Matching fields: ${item.searchMatch.matchingFields
                                          .map((field) => field.replace(/_/g, ' '))
                                          .join(', ')}`
                                    : item.summary}
                            </div>
                            <div>
                                <ExtraContext data={item.extraContextBottom} />
                            </div>
                        </div>
                    </>
                ) : (
                    <h5>{formattedName}</h5>
                )}
            </Link>
        )
    } else {
        content = (
            <>
                <div className="SidebarListItem__rename" ref={ref as React.RefObject<HTMLDivElement>}>
                    <input
                        value={newName || ''}
                        onChange={(e) => setNewName(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'ArrowDown') {
                                navigation3000Logic.actions.focusNextItem()
                                e.preventDefault()
                            } else if (e.key === 'ArrowUp') {
                                navigation3000Logic.actions.focusPreviousItem()
                                e.preventDefault()
                            } else if (e.key === 'Enter') {
                                void save(newName || '').then(() => {
                                    // In the keyboard nav experience, we need to refocus the item once it's a link again
                                    setTimeout(() => ref.current?.focus(), 0)
                                })
                                e.preventDefault()
                            } else if (e.key === 'Escape') {
                                cancel()
                                // In the keyboard nav experience, we need to refocus the item once it's a link again
                                setTimeout(() => ref.current?.focus(), 0)
                                e.preventDefault()
                            }
                        }}
                        onFocus={(e) => {
                            navigation3000Logic.actions.setLastFocusedItemByKey(
                                Array.isArray(item.key) ? item.key[0] : item.key
                            )
                            ;(e.target as HTMLInputElement).select()
                        }}
                        onBlur={(e) => {
                            if (e.relatedTarget?.ariaLabel === 'Save name') {
                                void save(newName || '')
                            } else {
                                cancel()
                            }
                        }}
                        placeholder={isItemTentative(item) ? 'Adding something new…' : `Renaming ${item.name}…`}
                        disabled={isSaving}
                        autoFocus
                    />
                </div>
                {newNameValidationError && <div className="SidebarListItem__error">{newNameValidationError}</div>}
            </>
        )
    }

    return (
        <li
            id={`sidebar-${item.key}`}
            title={!isItemTentative(item) && !isListItemAccordion(item) ? item.name : 'New item'}
            className={clsx(
                'SidebarListItem',
                'menuItems' in item && item.menuItems?.length && 'SidebarListItem--has-menu',
                isMenuOpen && 'SidebarListItem--is-menu-open',
                (isItemTentative(item) || newName !== null) && 'SidebarListItem--is-renaming',
                'marker' in item && !!item.marker && `SidebarListItem--marker-${item.marker.type}`,
                'marker' in item && !!item.marker?.status && `SidebarListItem--marker-status-${item.marker.status}`,
                'summary' in item && 'SidebarListItem--extended',
                isDragging && 'SidebarListItem--is-dragging'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={combinedStyle}
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            {...(isItemTentative(item) || isListItemAccordion(item) || !item.url ? { 'aria-disabled': true } : {})}
            {...(active ? { 'aria-current': 'page' } : {})}
            {...(newNameValidationError ? { 'aria-invalid': true } : {})}
        >
            {content}
            {isItemTentative(item) || newName !== null ? (
                <div className="SidebarListItem__actions">
                    {!isSaving && (
                        <LemonButton // This has no onClick, as the action is actually handled in the input's onBlur
                            size="small"
                            noPadding
                            icon={<IconX />}
                            tooltip={
                                <>
                                    Cancel <KeyboardShortcut escape />
                                </>
                            }
                            aria-label="Cancel"
                        />
                    )}
                    <LemonButton // This has no onClick, as the action is actually handled in the input's onBlur
                        size="small"
                        noPadding
                        icon={<IconCheckCircle />}
                        tooltip={
                            !isSaving ? (
                                <>
                                    Save name <KeyboardShortcut enter />
                                </>
                            ) : null
                        }
                        loading={isSaving}
                        aria-label="Save name"
                    />
                </div>
            ) : (
                !!menuItems?.length &&
                menuItemsVisible && (
                    <LemonMenu items={menuItems} onVisibilityChange={setIsMenuOpen}>
                        <div className="SidebarListItem__actions">
                            <LemonButton size="small" noPadding icon={<IconEllipsis />} />
                        </div>
                    </LemonMenu>
                )
            )}
        </li>
    )
}

/** Text with specified ranges highlighted by increased font weight. Great for higlighting search term matches. */
function TextWithHighlights({
    children,
    ranges,
}: {
    children: string
    ranges: readonly [number, number][]
}): JSX.Element {
    const segments: JSX.Element[] = []
    let previousBoldEnd = 0
    let segmentIndex = 0
    // Divide the item name into bold and regular segments
    for (let i = 0; i < ranges.length; i++) {
        const [currentBoldStart, currentBoldEnd] = ranges[i]
        if (currentBoldStart > previousBoldEnd) {
            segments.push(
                <React.Fragment key={segmentIndex}>{children.slice(previousBoldEnd, currentBoldStart)}</React.Fragment>
            )
            segmentIndex++
        }
        segments.push(<b key={segmentIndex}>{children.slice(currentBoldStart, currentBoldEnd)}</b>)
        segmentIndex++
        previousBoldEnd = currentBoldEnd
    }
    // If there is a non-highlighted segment left at the end, add it now
    if (previousBoldEnd < children.length) {
        segments.push(
            <React.Fragment key={segmentIndex}>{children.slice(previousBoldEnd, children.length)}</React.Fragment>
        )
    }

    return <>{segments}</>
}

/** Smart rendering of list item extra context. */
function ExtraContext({ data }: { data: ExtraListItemContext }): JSX.Element {
    return isDayjs(data) ? <TZLabel time={data} /> : <>{data}</>
}

function SidebarListItemSkeleton({ style }: { style: React.CSSProperties }): JSX.Element {
    return (
        <li
            className="SidebarListItem SidebarListItem__link"
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
        >
            <LemonSkeleton />
        </li>
    )
}

function SidebarListItemAccordion({
    category,
    onEditing,
}: {
    category: ListItemAccordion
    onEditing: (isEditing: boolean) => void
}): JSX.Element {
    const { listItemAccordionCollapseMapping } = useValues(navigation3000Logic)
    const { toggleListItemAccordion } = useActions(navigation3000Logic)
    const [isRenaming, setIsRenaming] = useState(false)
    const [newName, setNewName] = useState(category.name || capitalizeFirstLetter(pluralizeCategory(category.noun)))
    const [isSaving, setIsSaving] = useState(false)

    const ref = useRef<HTMLDivElement>(null)

    const { key } = category

    const keyString = Array.isArray(key) ? key.join(ITEM_KEY_PART_SEPARATOR) : key.toString()
    const isExpanded = !(keyString in listItemAccordionCollapseMapping) || !listItemAccordionCollapseMapping[keyString]

    const startRenaming = useCallback((): void => {
        if (category.onRename) {
            setIsRenaming(true)
        }
    }, [category.onRename])

    const cancelRenaming = (): void => {
        setIsRenaming(false)
        setNewName(category.name || capitalizeFirstLetter(pluralizeCategory(category.noun)))
    }

    const saveNewName = async (): Promise<void> => {
        if (category.onRename && newName !== category.name) {
            setIsSaving(true)
            try {
                await category.onRename(newName)
            } catch (error) {
                captureException(error)
                lemonToast.error('Could not rename item')
            } finally {
                setIsSaving(false)
                setIsRenaming(false)
            }
        } else {
            cancelRenaming()
        }
    }

    useEffect(() => {
        if (category.onRename && !isRenaming) {
            const onDoubleClick = (): void => {
                startRenaming()
            }
            const element = ref.current
            if (element) {
                element.addEventListener('dblclick', onDoubleClick)
                return () => {
                    element.removeEventListener('dblclick', onDoubleClick)
                }
            }
        }
    }, [isRenaming, category.onRename, startRenaming])

    useEffect(() => {
        onEditing(isRenaming)
    }, [isRenaming, onEditing])

    return (
        <li className="SidebarListItemAccordion" role="region" aria-expanded={isExpanded}>
            <div
                id={`sidebar-list-item-accordion-${keyString}`}
                className="SidebarListItemAccordion__header"
                role="button"
                aria-expanded={isExpanded}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--depth': category.depth } as React.CSSProperties}
                onClick={!isRenaming ? () => toggleListItemAccordion(keyString) : undefined}
                ref={ref}
            >
                <IconChevronRight />
                {isRenaming ? (
                    <div className="SidebarListItem__rename">
                        <input
                            value={newName}
                            onChange={(e) => setNewName(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    void saveNewName()
                                    e.preventDefault()
                                } else if (e.key === 'Escape') {
                                    cancelRenaming()
                                    e.preventDefault()
                                }
                            }}
                            onBlur={(e) => {
                                if (e.relatedTarget?.ariaLabel === 'Save name') {
                                    void saveNewName()
                                } else {
                                    cancelRenaming()
                                }
                            }}
                            placeholder="Renaming..."
                            disabled={isSaving}
                            autoFocus
                        />
                    </div>
                ) : (
                    <h4>{category.name || capitalizeFirstLetter(pluralizeCategory(category.noun))}</h4>
                )}
            </div>
        </li>
    )
}
