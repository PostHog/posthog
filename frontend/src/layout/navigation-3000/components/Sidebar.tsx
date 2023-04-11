import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'
import React from 'react'
import { navigation3000Logic } from '../navigationLogic'
import { KeyboardShortcut } from './KeyboardShortcut'
import { SidebarAccordion, SidebarList } from './SidebarAccordion'
import { Accordion, BasicListItem, ExtendedListItem } from '../types'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'

export function Sidebar(): JSX.Element {
    const {
        sidebarWidth: width,
        isSidebarShown: isShown,
        isResizeInProgress,
        sidebarOverslideDirection: overslideDirection,
        isSidebarKeyboardShortcutAcknowledged,
        activeNavbarItem,
    } = useValues(navigation3000Logic)
    const { beginResize } = useActions(navigation3000Logic)

    const { contents, activeListItemKey } = useValues(activeNavbarItem.pointer)

    const isLoading = true

    const content: JSX.Element | null =
        contents.length > 0 ? (
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
                <SidebarList
                    items={contents as BasicListItem[] | ExtendedListItem[]}
                    activeItemKey={activeListItemKey}
                />
            )
        ) : isLoading ? (
            <SpinnerOverlay />
        ) : null

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
                    <h3>{activeNavbarItem?.label}</h3>
                </div>
                <div className="Sidebar3000__lists">{content}</div>
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

export function SidebarKeyboardShortcut(): JSX.Element {
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
