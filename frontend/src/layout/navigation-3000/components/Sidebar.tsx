import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { LogicWrapper, useActions, useValues } from 'kea'
import { IconClose, IconMagnifier } from 'lib/lemon-ui/icons'
import React, { useRef, useState } from 'react'
import { navigation3000Logic } from '../navigationLogic'
import { KeyboardShortcut } from './KeyboardShortcut'
import { SidebarAccordion } from './SidebarAccordion'
import { SidebarCategory, SidebarLogic, SidebarNavbarItem } from '../types'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useDebouncedCallback } from 'use-debounce'

/** A small delay that prevents us from making a search request on each key press. */
const SEARCH_DEBOUNCE_MS = 300

/** Multi-segment item keys are joined using this separator for easy comparisons. */
const ITEM_KEY_PART_SEPARATOR = '::'

interface SidebarProps {
    navbarItem: SidebarNavbarItem // Sidebar can only be rendered if there's an active sidebar navbar item
}
export function Sidebar({ navbarItem }: SidebarProps): JSX.Element {
    const inputElementRef = useRef<HTMLInputElement>(null)

    const {
        sidebarWidth: width,
        isSidebarShown: isShown,
        isResizeInProgress,
        sidebarOverslideDirection: overslideDirection,
        isSidebarKeyboardShortcutAcknowledged,
        isSearchShown,
    } = useValues(navigation3000Logic({ inputElement: inputElementRef.current }))
    const { beginResize, setIsSearchShown } = useActions(navigation3000Logic({ inputElement: inputElementRef.current }))
    const { contents } = useValues(navbarItem.logic)

    const title =
        contents.length !== 1 || contents[0].title === navbarItem.label
            ? navbarItem.label
            : `${navbarItem.label} — ${contents[0].title}`

    return (
        <div
            className={clsx(
                'Sidebar3000',
                isResizeInProgress && 'Sidebar3000--resizing',
                overslideDirection && `Sidebar3000--overslide-${overslideDirection}`
            )}
            aria-hidden={!isShown}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--sidebar-width': `${isShown ? width : 0}px`,
                } as React.CSSProperties
            }
        >
            <div className="Sidebar3000__content">
                <div className="Sidebar3000__header">
                    <h3 className="grow">{title}</h3>
                    <LemonButton
                        icon={<IconMagnifier />}
                        size="small"
                        noPadding
                        onClick={() => setIsSearchShown(!isSearchShown)}
                        active={isSearchShown}
                        tooltip={
                            <>
                                Find <KeyboardShortcut shift command f />
                            </>
                        }
                        tooltipPlacement="bottom"
                    />
                </div>
                {navbarItem?.logic && isSearchShown && (
                    <SidebarSearchBar activeSidebarLogic={navbarItem.logic} inputElementRef={inputElementRef} />
                )}
                <div className="Sidebar3000__lists">
                    {navbarItem?.logic && <SidebarContent activeSidebarLogic={navbarItem.logic} />}
                </div>
                {!isSidebarKeyboardShortcutAcknowledged && <SidebarKeyboardShortcut />}
            </div>
            <div
                className="Sidebar3000__slider"
                onMouseDown={(e) => {
                    if (e.button === 0) {
                        beginResize()
                    }
                }}
            />
        </div>
    )
}

function SidebarSearchBar({
    activeSidebarLogic,
    inputElementRef,
}: {
    activeSidebarLogic: LogicWrapper<SidebarLogic>
    inputElementRef: React.RefObject<HTMLInputElement>
}): JSX.Element {
    const { searchTerm } = useValues(navigation3000Logic)
    const { setIsSearchShown, setSearchTerm, focusNextItem, setLastFocusedItemIndex } = useActions(navigation3000Logic)
    const { contents, debounceSearch } = useValues(activeSidebarLogic)

    const [localSearchTerm, setLocalSearchTerm] = useState(searchTerm)
    const setSearchTermDebounced = useDebouncedCallback(
        (value: string) => setSearchTerm(value),
        debounceSearch ? SEARCH_DEBOUNCE_MS : undefined
    )

    const isLoading = contents.some((item) => item.loading)

    return (
        <div>
            <LemonInput
                ref={inputElementRef}
                type="search"
                value={localSearchTerm}
                onChange={(value) => {
                    setLocalSearchTerm(value)
                    setSearchTermDebounced(value)
                }}
                size="small"
                // Show a loading spinner when search term is being debounced or just loading data
                prefix={
                    (localSearchTerm || searchTerm) && (localSearchTerm !== searchTerm || isLoading) ? (
                        <Spinner textColored />
                    ) : null
                }
                placeholder="Search..."
                onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                        setIsSearchShown(false)
                        e.preventDefault()
                    } else if (e.key === 'ArrowDown') {
                        focusNextItem()
                        e.preventDefault()
                    }
                }}
                onFocus={() => {
                    setLastFocusedItemIndex(-1)
                }}
                autoFocus
                suffix={<KeyboardShortcut muted arrowdown arrowup />}
            />
        </div>
    )
}

function SidebarContent({
    activeSidebarLogic,
}: {
    activeSidebarLogic: LogicWrapper<SidebarLogic>
}): JSX.Element | null {
    const { accordionCollapseMapping } = useValues(navigation3000Logic)
    const { toggleAccordion } = useActions(navigation3000Logic)
    const { contents, activeListItemKey } = useValues(activeSidebarLogic)

    const normalizedActiveItemKey = Array.isArray(activeListItemKey)
        ? activeListItemKey.join(ITEM_KEY_PART_SEPARATOR)
        : activeListItemKey

    return contents.length !== 1 ? (
        <>
            {(contents as SidebarCategory[]).map((accordion) => (
                <SidebarAccordion
                    key={accordion.key}
                    title={accordion.title}
                    items={accordion.items.map((item) => ({
                        ...item,
                        // Normalize keys in-place so that item refs can be injected later during rendering
                        key: Array.isArray(item.key)
                            ? item.key.map((keyPart) => `${accordion.key}${ITEM_KEY_PART_SEPARATOR}${keyPart}`)
                            : `${accordion.key}${ITEM_KEY_PART_SEPARATOR}${item.key}`,
                    }))}
                    remote={accordion.remote}
                    loading={accordion.loading}
                    collapsed={accordionCollapseMapping[accordion.key]}
                    toggle={() => toggleAccordion(accordion.key)}
                    activeItemKey={normalizedActiveItemKey ?? null}
                />
            ))}
        </>
    ) : (
        <SidebarAccordion
            key={contents[0].key}
            title={contents[0].title}
            items={contents[0].items}
            remote={contents[0].remote}
            loading={contents[0].loading}
            activeItemKey={normalizedActiveItemKey ?? null}
        />
    )
}

function SidebarKeyboardShortcut(): JSX.Element {
    const { acknowledgeSidebarKeyboardShortcut } = useActions(navigation3000Logic)

    return (
        <div className="Sidebar3000__hint">
            <span className="truncate">
                <i>Tip:</i> Press <KeyboardShortcut command b /> to toggle this sidebar
            </span>
            <LemonButton
                icon={<IconClose />}
                size="small"
                onClick={() => acknowledgeSidebarKeyboardShortcut()}
                noPadding
            />
        </div>
    )
}
