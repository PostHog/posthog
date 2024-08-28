import { IconSearch, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { LogicWrapper, useActions, useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter } from 'lib/utils'
import React, { useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { navigation3000Logic } from '../navigationLogic'
import { SidebarLogic, SidebarNavbarItem } from '../types'
import { KeyboardShortcut } from './KeyboardShortcut'
import { NewItemButton } from './NewItemButton'
import { pluralizeCategory, SidebarAccordion } from './SidebarAccordion'
import { SidebarList } from './SidebarList'

/** A small delay that prevents us from making a search request on each key press. */
const SEARCH_DEBOUNCE_MS = 300

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
    const { beginResize } = useActions(navigation3000Logic({ inputElement: inputElementRef.current }))
    const { contents } = useValues(navbarItem.logic)

    const onlyCategoryTitle = contents.length === 1 ? capitalizeFirstLetter(pluralizeCategory(contents[0].noun)) : null
    const title =
        !onlyCategoryTitle || onlyCategoryTitle.toLowerCase() === navbarItem.label.toLowerCase()
            ? navbarItem.label
            : `${navbarItem.label} — ${onlyCategoryTitle}`

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
                    <SidebarActions activeSidebarLogic={navbarItem.logic} />
                </div>
                {navbarItem?.logic && isSearchShown && (
                    <SidebarSearchBar activeSidebarLogic={navbarItem.logic} inputElementRef={inputElementRef} />
                )}
                <div className="Sidebar3000__lists">
                    {navbarItem?.logic && <SidebarContent activeSidebarLogic={navbarItem.logic} />}
                </div>
                {!isSidebarKeyboardShortcutAcknowledged && <SidebarKeyboardShortcut />}
                {contents
                    .filter(({ modalContent }) => modalContent)
                    .map((category) => (
                        <React.Fragment key={category.key}>{category.modalContent}</React.Fragment>
                    ))}
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

function SidebarActions({ activeSidebarLogic }: { activeSidebarLogic: LogicWrapper<SidebarLogic> }): JSX.Element {
    const { isSearchShown } = useValues(navigation3000Logic)
    const { setIsSearchShown } = useActions(navigation3000Logic)
    const { contents } = useValues(activeSidebarLogic)

    return (
        <>
            {contents.length === 1 && (
                // If there's only one category, show a top level "New" button
                <NewItemButton category={contents[0]} />
            )}
            <LemonButton
                icon={<IconSearch />}
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
        </>
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
                inputRef={inputElementRef}
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
    const { contents } = useValues(activeSidebarLogic)

    return contents.length !== 1 ? (
        <>
            {contents.map((accordion) => (
                <SidebarAccordion key={accordion.key} category={accordion} />
            ))}
        </>
    ) : (
        <SidebarList category={contents[0]} />
    )
}

function SidebarKeyboardShortcut(): JSX.Element {
    const { acknowledgeSidebarKeyboardShortcut } = useActions(navigation3000Logic)

    return (
        <div className="Sidebar3000__hint">
            <span className="truncate">
                <i>Tip:</i> Press <KeyboardShortcut command b /> to toggle this sidebar
            </span>
            <LemonButton icon={<IconX />} size="small" onClick={() => acknowledgeSidebarKeyboardShortcut()} noPadding />
        </div>
    )
}
