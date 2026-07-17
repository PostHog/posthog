import { useActions, useValues } from 'kea'
import React from 'react'

import {
    IconChevronLeft,
    IconChevronRight,
    IconCopy,
    IconExternal,
    IconPencil,
    IconPin,
    IconPinFilled,
    IconPlus,
    IconX,
} from '@posthog/icons'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'

import { DesktopSceneTab, sceneTabsLogic } from '~/layout/scenes/sceneTabsLogic'

interface SceneTabContextMenuProps {
    tab: DesktopSceneTab
    children: React.ReactElement
}

export function SceneTabContextMenu({ tab, children }: SceneTabContextMenuProps): JSX.Element {
    const { tabs } = useValues(sceneTabsLogic)
    const { setTabs, removeTab, freezeTabWidths, duplicateTab, startTabEdit, pinTab, unpinTab, newTab } =
        useActions(sceneTabsLogic)

    const tabUrl = `${window.location.origin}${tab.pathname}${tab.search}${tab.hash}`

    const openInNewWindow = (): void => {
        // In the desktop app the main process intercepts window.open for the local
        // origin and opens a new PostHog window
        window.open(tabUrl, '_blank', 'noopener,noreferrer')
    }

    const closeToLeft = (): void => {
        const idx = tabs.findIndex((t) => t.id === tab.id)
        if (idx === -1) {
            return
        }
        setTabs(tabs.slice(idx))
    }

    const closeToRight = (): void => {
        const idx = tabs.findIndex((t) => t.id === tab.id)
        if (idx === -1) {
            return
        }
        setTabs(tabs.slice(0, idx + 1))
    }

    return (
        <ContextMenu>
            <ContextMenuTrigger>{children}</ContextMenuTrigger>
            <ContextMenuContent className="max-w-[300px]">
                <ContextMenuGroup>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => newTab(`${tab.pathname}${tab.search}${tab.hash}`, { activate: false })}
                        >
                            <IconPlus /> Open copy in new tab
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={openInNewWindow}>
                            <IconExternal /> Open in new window
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuSeparator />
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => (tab.pinned ? unpinTab(tab.id) : pinTab(tab.id))}>
                            {tab.pinned ? <IconPinFilled /> : <IconPin />} {tab.pinned ? 'Unpin tab' : 'Pin tab'}
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => duplicateTab(tab)}>
                            <IconCopy /> Duplicate tab
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => {
                                try {
                                    navigator.clipboard.writeText(tabUrl)
                                    lemonToast.success('URL copied to clipboard')
                                } catch (error) {
                                    lemonToast.error(`Failed to copy URL to clipboard ${error}`)
                                }
                            }}
                        >
                            <IconCopy /> Copy URL
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => startTabEdit(tab)}>
                            <IconPencil /> Rename tab
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuSeparator />
                    <ContextMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => {
                                freezeTabWidths()
                                removeTab(tab, { source: 'context_menu' })
                            }}
                        >
                            <IconX /> Close tab
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={closeToLeft}>
                            <IconChevronLeft /> Close tabs to the left
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={closeToRight}>
                            <IconChevronRight /> Close tabs to the right
                        </ButtonPrimitive>
                    </ContextMenuItem>
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}
