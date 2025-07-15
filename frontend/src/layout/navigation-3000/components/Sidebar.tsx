import { LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { LogicWrapper, useActions, useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import React, { useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { navigation3000Logic } from '../navigationLogic'
import { SidebarLogic, SidebarNavbarItem } from '../types'
import { SidebarAccordion } from './SidebarAccordion'
import { SidebarList } from './SidebarList'

/** A small delay that prevents us from making a search request on each key press. */
const SEARCH_DEBOUNCE_MS = 300

interface SidebarProps {
    navbarItem: SidebarNavbarItem // Sidebar can only be rendered if there's an active sidebar navbar item
    sidebarOverlay?: React.ReactNode
    sidebarOverlayProps?: SidebarOverlayProps
}

interface SidebarOverlayProps {
    className?: string
    isOpen?: boolean
}

export function Sidebar({ navbarItem, sidebarOverlay, sidebarOverlayProps }: SidebarProps): JSX.Element {
    const inputElementRef = useRef<HTMLInputElement>(null)

    const {
        sidebarWidth: width,
        isSidebarShown: isShown,
        isResizeInProgress,
        sidebarOverslideDirection: overslideDirection,
        isSearchShown,
    } = useValues(navigation3000Logic({ inputElement: inputElementRef.current }))
    const { contents } = useValues(navbarItem.logic)

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
                {navbarItem?.logic && isSearchShown && (
                    <SidebarSearchBar activeSidebarLogic={navbarItem.logic} inputElementRef={inputElementRef} />
                )}
                <div className="Sidebar3000__lists">
                    {navbarItem?.logic && <SidebarContent activeSidebarLogic={navbarItem.logic} />}
                </div>
                {contents
                    .filter(({ modalContent }) => modalContent)
                    .map((category) => (
                        <React.Fragment key={category.key}>{category.modalContent}</React.Fragment>
                    ))}
            </div>
            {sidebarOverlay && (
                <SidebarOverlay {...sidebarOverlayProps} isOpen={sidebarOverlayProps?.isOpen && isShown} width={width}>
                    {sidebarOverlay}
                </SidebarOverlay>
            )}
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
    const { setSearchTerm, focusNextItem, setLastFocusedItemIndex } = useActions(navigation3000Logic)
    const { contents, debounceSearch } = useValues(activeSidebarLogic)

    const [localSearchTerm, setLocalSearchTerm] = useState(searchTerm)
    const setSearchTermDebounced = useDebouncedCallback(
        (value: string) => setSearchTerm(value),
        debounceSearch ? SEARCH_DEBOUNCE_MS : undefined
    )

    const isLoading = contents.some((item) => item.loading)

    return (
        <div className="h-8 m-1.5">
            <LemonInput
                className="rounded-md border border-border"
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
                    if (e.key === 'ArrowDown') {
                        focusNextItem()
                        e.preventDefault()
                    }
                }}
                onFocus={() => {
                    setLastFocusedItemIndex(-1)
                }}
                autoFocus
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

function SidebarOverlay({
    className,
    isOpen = false,
    children,
    width,
}: SidebarOverlayProps & { children: React.ReactNode; width: number }): JSX.Element | null {
    if (!isOpen) {
        return null
    }

    return (
        <div
            className={clsx('absolute top-0 left-0 h-full bg-primary z-10', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: `${width}px` }}
        >
            {children}
        </div>
    )
}
