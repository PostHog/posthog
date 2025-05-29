import { IconCheckCircle, IconEllipsis, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, lemonToast } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useAsyncActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { isDayjs } from 'lib/dayjs'
import { IconChevronRight } from 'lib/lemon-ui/icons/icons'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils'
import posthog from 'posthog-js'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { InfiniteLoader } from 'react-virtualized/dist/es/InfiniteLoader'
import { List, ListProps } from 'react-virtualized/dist/es/List'

import { SearchHighlight } from '~/layout/navigation-3000/components/SearchHighlight'

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

    const emptyStateSkeletonCount = useMemo(() => 4 + Math.floor(Math.random() * 4), [])

    const { items: _items } = category

    const listItems = useMemo(() => {
        const allItems: (BasicListItem | ExtendedListItem | ListItemAccordion)[] = []

        const flatten = (
            items: BasicListItem[] | ExtendedListItem[] | ListItemAccordion[],
            depth: number = 1,
            parentKey: string | number | string[] | null = null
        ): void => {
            items.forEach((item) => {
                allItems.push({
                    ...item,
                    depth: depth,
                    key: parentKey
                        ? [
                              Array.isArray(parentKey) ? parentKey.join(ITEM_KEY_PART_SEPARATOR) : parentKey,
                              item.key,
                          ].join(ITEM_KEY_PART_SEPARATOR)
                        : item.key.toString(),
                })
                if (isListItemAccordion(item)) {
                    flatten(
                        item.items,
                        depth + 1,
                        parentKey ? `${parentKey}${ITEM_KEY_PART_SEPARATOR}${item.key}` : item.key
                    )
                }
            })
        }

        flatten(_items, 1, category.key)

        return allItems.filter((item) =>
            isListItemVisible(Array.isArray(item.key) ? item.key.join(ITEM_KEY_PART_SEPARATOR) : item.key.toString())
        )
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

            const normalizedItemKey = Array.isArray(item.key)
                ? item.key.map((keyPart) => `${category.key}${ITEM_KEY_PART_SEPARATOR}${keyPart}`)
                : `${category.key}${ITEM_KEY_PART_SEPARATOR}${item.key}`

            let active: boolean
            if (Array.isArray(normalizedItemKey)) {
                active =
                    typeof normalizedActiveListItemKey === 'string' &&
                    normalizedItemKey.includes(normalizedActiveListItemKey)
            } else {
                active = normalizedItemKey === normalizedActiveListItemKey
            }
            return <SidebarListItem key={index} item={item} validateName={validateName} active={active} style={style} />
        },
        overscanRowCount: 20,
        tabIndex: null,
    } as ListProps
    return (
        // The div is for AutoSizer to work
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
                            loadMoreRows={({ startIndex, stopIndex }) => remote.loadMoreItems(startIndex, stopIndex)}
                            rowCount={remote.itemCount}
                            minimumBatchSize={remote.minimumBatchSize || 100} // Sync default with the REST_FRAMEWORK PAGE_SIZE setting
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

function SidebarListItem({ item, validateName, active, style }: SidebarListItemProps): JSX.Element {
    const [isMenuOpen, setIsMenuOpen] = useState(false)
    const [newName, setNewName] = useState<null | string>(null)
    const [newNameValidationError, setNewNameValidationError] = useState<null | string>(null)
    const [isSavingName, setIsSavingName] = useState(false)

    const ref = useRef<HTMLElement | null>(null)
    item.ref = ref // Inject ref for keyboard navigation

    const isSaving = isItemTentative(item) ? item.loading : isSavingName

    const menuItems = useMemo(() => {
        if (isItemTentative(item) || isListItemAccordion(item)) {
            return undefined
        }
        if (item.onRename) {
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
    const save = isItemTentative(item)
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
                  posthog.captureException(error)
                  lemonToast.error('Could not rename item')
              } finally {
                  setIsSavingName(false)
                  cancel()
              }
          }
        : null

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
    }) // Intentionally run on every render so that ref value changes are picked up

    let content: JSX.Element
    if (isListItemAccordion(item)) {
        content = <SidebarListItemAccordion category={item} />
    } else if (isItemClickable(item)) {
        content = (
            <div
                className="SidebarListItem__button"
                onClick={item.onClick}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--depth': item.depth } as React.CSSProperties}
            >
                {item.icon && <div className="SidebarListItem__icon">{item.icon}</div>}
                <SearchHighlight string={item.name} substring={navigation3000Logic.values.searchTerm} />
            </div>
        )
    } else if (!save || (!isItemTentative(item) && newName === null)) {
        if (isItemTentative(item)) {
            throw new Error('Tentative items should not be rendered in read mode')
        }
        let formattedName = item.searchMatch?.nameHighlightRanges?.length ? (
            <SearchHighlight string={item.name} substring={navigation3000Logic.values.searchTerm} />
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
                'summary' in item && 'SidebarListItem--extended'
            )}
            aria-disabled={!isItemTentative(item) && !isListItemAccordion(item) && !item.url}
            aria-current={active ? 'page' : undefined}
            aria-invalid={!!newNameValidationError}
            style={style} // eslint-disable-line react/forbid-dom-props
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
                !!menuItems?.length && (
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

/** Smart rendering of list item extra context. */
function ExtraContext({ data }: { data: ExtraListItemContext }): JSX.Element {
    return isDayjs(data) ? <TZLabel time={data} /> : <>{data}</>
}

function SidebarListItemSkeleton({ style }: { style: React.CSSProperties }): JSX.Element {
    return (
        <li
            className="SidebarListItem SidebarListItem__link"
            style={style} // eslint-disable-line react/forbid-dom-props
        >
            <LemonSkeleton />
        </li>
    )
}

function SidebarListItemAccordion({ category }: { category: ListItemAccordion }): JSX.Element {
    const { listItemAccordionCollapseMapping } = useValues(navigation3000Logic)
    const { toggleListItemAccordion } = useActions(navigation3000Logic)

    const { key, items } = category

    const isEmpty = items.length === 0
    const keyString = Array.isArray(key) ? key.join(ITEM_KEY_PART_SEPARATOR) : key.toString()
    const isExpanded = !(keyString in listItemAccordionCollapseMapping) || !listItemAccordionCollapseMapping[keyString]

    return (
        <div className="SidebarListItemAccordion" role="region" aria-expanded={isExpanded}>
            <div
                id={`sidebar-list-item-accordion-${keyString}`}
                className="SidebarListItemAccordion__header"
                role="button"
                aria-expanded={isExpanded}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--depth': category.depth } as React.CSSProperties}
                onClick={isExpanded || items.length > 0 ? () => toggleListItemAccordion(keyString) : undefined}
            >
                <IconChevronRight />
                {category.icon && <div className="SidebarListItemAccordion__icon">{category.icon}</div>}
                <h4>
                    {capitalizeFirstLetter(pluralizeCategory(category.noun))}
                    {isEmpty && (
                        <>
                            {' '}
                            <i>(empty)</i>
                        </>
                    )}
                </h4>
            </div>
        </div>
    )
}
