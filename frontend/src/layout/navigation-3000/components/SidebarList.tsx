import { Link, TZLabel } from '@posthog/apps-common'
import clsx from 'clsx'
import { isDayjs } from 'lib/dayjs'
import { IconCheckmark, IconClose, IconEllipsis } from 'lib/lemon-ui/icons'
import { BasicListItem, ExtendedListItem, ExtraListItemContext, SidebarCategory } from '../types'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonButton, LemonTag, lemonToast } from '@posthog/lemon-ui'
import { navigation3000Logic } from '../navigationLogic'
import { captureException } from '@sentry/react'
import { KeyboardShortcut } from './KeyboardShortcut'
import { List, ListProps } from 'react-virtualized/dist/es/List'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { InfiniteLoader } from 'react-virtualized/dist/es/InfiniteLoader'
import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function SidebarList({
    items,
    activeItemKey,
    remote,
}: {
    items: BasicListItem[] | ExtendedListItem[]
    activeItemKey: string | number | null
    remote?: SidebarCategory['remote']
}): JSX.Element {
    const { sidebarWidth } = useValues(navigation3000Logic)

    const firstItem = items.find(Boolean)
    const usingExtendedItemFormat = !!firstItem && 'summary' in firstItem

    const listProps = {
        className: 'SidebarList',
        width: sidebarWidth,
        rowHeight: usingExtendedItemFormat ? 46 : 32,
        rowRenderer: ({ index, style }) => {
            const item = items[index]
            if (!item) {
                return <SidebarListItemSkeleton key={index} style={style} />
            }
            let active: boolean
            if (Array.isArray(item.key)) {
                active = typeof activeItemKey === 'string' ? item.key.includes(activeItemKey) : false
            } else {
                active = item.key === activeItemKey
            }
            return <SidebarListItem key={index} item={item} active={active} style={style} />
        },
        overscanRowCount: 20,
        tabIndex: null,
    } as ListProps

    return (
        // The div is for AutoSizer to work
        <div className="flex-1">
            <AutoSizer disableWidth>
                {({ height }) =>
                    remote ? (
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
                                    rowCount={remote.itemCount}
                                    onRowsRendered={onRowsRendered}
                                />
                            )}
                        </InfiniteLoader>
                    ) : (
                        <List {...listProps} height={height} rowCount={items.length} />
                    )
                }
            </AutoSizer>
        </div>
    )
}

function SidebarListItem({
    item,
    active,
    style,
}: {
    item: BasicListItem | ExtendedListItem
    active: boolean
    style: React.CSSProperties
}): JSX.Element {
    const [isMenuOpen, setIsMenuOpen] = useState(false)
    const [renamingName, setRenamingName] = useState<null | string>(null)
    const [isSavingName, setIsSavingName] = useState(false)
    const ref = useRef<HTMLElement | null>(null)
    item.ref = ref // Inject ref for keyboard navigation

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

    const { onRename } = item
    const menuItems = useMemo(() => {
        if (item.onRename) {
            if (typeof item.menuItems !== 'function') {
                throw new Error('menuItems must be a function for renamable items so that the "Rename" item is shown')
            }
            return item.menuItems(() => setRenamingName(item.name))
        }
        return typeof item.menuItems === 'function'
            ? item.menuItems(() => console.error('Cannot rename item without onRename handler'))
            : item.menuItems
    }, [item, setRenamingName])

    const completeRename = onRename
        ? async (newName: string): Promise<void> => {
              if (!newName || newName === item.name) {
                  // No change to be saved
                  setRenamingName(null)
                  return
              }
              setIsSavingName(true)
              try {
                  await onRename(newName)
              } catch (error) {
                  captureException(error)
                  lemonToast.error('Could not rename item')
              } finally {
                  setIsSavingName(false)
                  setRenamingName(null)
              }
          }
        : null

    useEffect(() => {
        // Add double-click handler for renaming
        if (completeRename && renamingName === null) {
            const onDoubleClick = (): void => {
                setRenamingName(item.name)
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

    const content =
        !completeRename || renamingName === null ? (
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
                    } else if (completeRename && e.key === 'Enter') {
                        setRenamingName(item.name)
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
        ) : (
            <div className="SidebarListItem__rename" ref={ref as React.RefObject<HTMLDivElement>}>
                <input
                    value={renamingName}
                    onChange={(e) => setRenamingName(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'ArrowDown') {
                            navigation3000Logic.actions.focusNextItem()
                            e.preventDefault()
                        } else if (e.key === 'ArrowUp') {
                            navigation3000Logic.actions.focusPreviousItem()
                            e.preventDefault()
                        } else if (e.key === 'Enter') {
                            completeRename(renamingName).then(() => {
                                // In the keyboard nav experience, we need to refocus the item once it's a link again
                                setTimeout(() => ref.current?.focus(), 0)
                            })
                            e.preventDefault()
                        } else if (e.key === 'Escape') {
                            setRenamingName(null)
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
                            completeRename(renamingName)
                        } else {
                            setRenamingName(null)
                        }
                    }}
                    disabled={isSavingName}
                    autoFocus
                />
            </div>
        )

    return (
        <li
            id={`sidebar-${item.key}`}
            title={item.name}
            className={clsx(
                'SidebarListItem',
                !!item.menuItems?.length && 'SidebarListItem--has-menu',
                isMenuOpen && 'SidebarListItem--is-menu-open',
                renamingName !== null && 'SidebarListItem--is-renaming',
                !!item.marker && `SidebarListItem--marker-${item.marker.type}`,
                !!item.marker?.status && `SidebarListItem--marker-status-${item.marker.status}`,
                'summary' in item && 'SidebarListItem--extended'
            )}
            aria-disabled={!item.url}
            aria-current={active ? 'page' : undefined}
            style={style} // eslint-disable-line react/forbid-dom-props
        >
            {content}
            {renamingName !== null ? (
                <div className="SidebarListItem__actions">
                    {!isSavingName && (
                        <LemonButton // This has no onClick, as the action is actually handled in the input's onBlur
                            size="small"
                            noPadding
                            icon={<IconClose />}
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
                        icon={<IconCheckmark />}
                        tooltip={
                            !isSavingName ? (
                                <>
                                    Save name <KeyboardShortcut enter />
                                </>
                            ) : null
                        }
                        loading={isSavingName}
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
            style={style} // eslint-disable-line react/forbid-dom-props
        >
            <LemonSkeleton />
        </li>
    )
}
