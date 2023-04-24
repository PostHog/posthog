import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { LogicWrapper, useActions, useValues } from 'kea'
import { IconClose, IconMagnifier } from 'lib/lemon-ui/icons'
import React from 'react'
import { SIDEBAR_SEARCH_INPUT_ID, navigation3000Logic } from '../navigationLogic'
import { KeyboardShortcut } from './KeyboardShortcut'
import { SidebarAccordion, SidebarList } from './SidebarAccordion'
import { Accordion, BasicListItem, ExtendedListItem, SidebarLogic } from '../types'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'

export function Sidebar(): JSX.Element {
    const {
        sidebarWidth: width,
        isSidebarShown: isShown,
        isResizeInProgress,
        sidebarOverslideDirection: overslideDirection,
        isSidebarKeyboardShortcutAcknowledged,
        activeNavbarItem,
        isSearchShown,
        searchTerm,
    } = useValues(navigation3000Logic)
    const { beginResize, setIsSearchShown, setSearchTerm } = useActions(navigation3000Logic)

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
                    <h3 className="grow">{activeNavbarItem?.label}</h3>
                    {setIsSearchShown && (
                        <LemonButton
                            icon={<IconMagnifier />}
                            size="small"
                            onClick={() => setIsSearchShown(!isSearchShown)}
                            active={isSearchShown}
                            tooltip={
                                <>
                                    Find <KeyboardShortcut shift command f />
                                </>
                            }
                        />
                    )}
                </div>
                {isSearchShown && (
                    <div>
                        <LemonInput
                            id={SIDEBAR_SEARCH_INPUT_ID}
                            type="search"
                            value={searchTerm as string}
                            onChange={(value) => setSearchTerm(value)}
                            size="small"
                            placeholder="Search..."
                            autoFocus
                        />
                    </div>
                )}
                <div className="Sidebar3000__lists">
                    <SidebarContent activeSidebarLogic={activeNavbarItem.pointer} />
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

function SidebarContent({
    activeSidebarLogic,
}: {
    activeSidebarLogic: LogicWrapper<SidebarLogic>
}): JSX.Element | null {
    const { contents, activeListItemKey, isLoading } = useValues(activeSidebarLogic)

    return contents.length > 0 ? (
        'items' in contents[0] ? (
            <>
                {(contents as Accordion[]).map((accordion) => (
                    <SidebarAccordion
                        key={accordion.title}
                        title={accordion.title}
                        items={accordion.items}
                        // TODO loading={accordion.loading}
                        activeItemKey={activeListItemKey}
                    />
                ))}
            </>
        ) : (
            <SidebarList items={contents as BasicListItem[] | ExtendedListItem[]} activeItemKey={activeListItemKey} />
        )
    ) : isLoading ? (
        <SpinnerOverlay />
    ) : null
}

function SidebarKeyboardShortcut(): JSX.Element {
    const { acknowledgeSidebarKeyboardShortcut } = useActions(navigation3000Logic)

    return (
        <div className="Sidebar3000__hint">
            <span className="truncate">
                <i>Tip:</i> Press <KeyboardShortcut command b /> to toggle this sidebar
            </span>
            <LemonButton icon={<IconClose />} size="small" onClick={() => acknowledgeSidebarKeyboardShortcut()} />
        </div>
    )
}
