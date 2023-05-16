import { Link, TZLabel } from '@posthog/apps-common'
import clsx from 'clsx'
import { isDayjs } from 'lib/dayjs'
import { IconChevronRight, IconEllipsis } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import React, { useState } from 'react'
import { BasicListItem, ExtendedListItem, ExtraListItemContext } from '../types'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonButton } from '@posthog/lemon-ui'
import { navigation3000Logic } from '../navigationLogic'

interface SidebarAccordionProps {
    title: string
    items: BasicListItem[] | ExtendedListItem[]
    activeItemKey: BasicListItem['key'] | null
    loading?: boolean
}

export function SidebarAccordion({ title, items, activeItemKey, loading = false }: SidebarAccordionProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    const isEmpty = items.length === 0
    const isEmptyDefinitively = !loading && isEmpty
    const isDisabled = isEmpty && !isExpanded

    return (
        <section className={clsx('Accordion', isExpanded && 'Accordion--expanded')} aria-disabled={isDisabled}>
            <div
                className="Accordion__header"
                onClick={isExpanded || items.length > 0 ? () => setIsExpanded(!isExpanded) : undefined}
            >
                {!loading ? <IconChevronRight /> : <Spinner />}
                <h4>
                    {title}
                    {isEmptyDefinitively && (
                        <>
                            {' '}
                            <i>(empty)</i>
                        </>
                    )}
                </h4>
            </div>
            {isExpanded && (
                <div className="Accordion__content">
                    <div className="Accordion__meta">Name</div>
                    <SidebarList items={items} activeItemKey={activeItemKey} />
                </div>
            )}
        </section>
    )
}

export function SidebarList({
    items,
    activeItemKey,
}: {
    items: BasicListItem[] | ExtendedListItem[]
    activeItemKey: BasicListItem['key'] | null
}): JSX.Element {
    return (
        <ul className="SidebarList">
            {items.map((item) => (
                <SidebarListItem key={item.key} item={item} active={item.key === activeItemKey} />
            ))}
        </ul>
    )
}

function SidebarListItem({ item, active }: { item: BasicListItem | ExtendedListItem; active: boolean }): JSX.Element {
    const [isMenuOpen, setIsMenuOpen] = useState(false)

    const formattedName = item.searchMatch?.nameHighlightRanges?.length ? (
        <TextWithHighlights ranges={item.searchMatch.nameHighlightRanges}>{item.name}</TextWithHighlights>
    ) : (
        item.name
    )

    if (!item.ref) {
        item.ref = React.createRef()
    }

    return (
        <li
            title={item.name}
            className={clsx(
                'SidebarListItem',
                !!item.menuItems && 'SidebarListItem--has-menu',
                isMenuOpen && 'SidebarListItem--is-menu-open',
                !!item.marker && `SidebarListItem--marker-${item.marker.type}`,
                !!item.marker?.status && `SidebarListItem--marker-status-${item.marker.status}`,
                'summary' in item && 'SidebarListItem--extended'
            )}
            aria-current={active ? 'page' : undefined}
        >
            <Link
                to={item.url}
                className="SidebarListItem__link"
                ref={item.ref}
                onKeyDown={(e) => {
                    if (e.key === 'ArrowDown') {
                        navigation3000Logic.actions.focusNextItem()
                        e.preventDefault()
                    } else if (e.key === 'ArrowUp') {
                        navigation3000Logic.actions.focusPreviousItem()
                        e.preventDefault()
                    }
                }}
                onFocus={() => {
                    navigation3000Logic.actions.setLastFocusedItemByKey(item.key)
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
                                {item.searchMatch
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
            {item.menuItems && (
                <LemonMenu items={item.menuItems} onVisibilityChange={setIsMenuOpen}>
                    <div className="SidebarListItem__menu">
                        <LemonButton size="small" icon={<IconEllipsis />} />
                    </div>
                </LemonMenu>
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
