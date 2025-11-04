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
    IconX,
} from '@posthog/icons'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { SceneTab } from 'scenes/sceneTypes'

import { sceneLogic } from '~/scenes/sceneLogic'

import { KeyboardShortcut } from '../navigation-3000/components/KeyboardShortcut'

export function SceneTabContextMenu({ tab, children }: { tab: SceneTab; children: React.ReactElement }): JSX.Element {
    const { tabs } = useValues(sceneLogic)
    const { setTabs, removeTab, duplicateTab, startTabEdit, pinTab, unpinTab } = useActions(sceneLogic)

    const openInNewWindow = (): void => {
        const fullUrl = `${window.location.origin}${tab.pathname}${tab.search}${tab.hash}`
        window.open(fullUrl, '_blank', 'noopener,noreferrer')
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
            <ContextMenuContent>
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
                                navigator.clipboard.writeText(
                                    `${window.location.origin}${tab.pathname}${tab.search}${tab.hash}`
                                )
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
                <ContextMenuItem asChild>
                    <ButtonPrimitive menuItem onClick={openInNewWindow}>
                        <IconExternal /> Open in new browser tab
                    </ButtonPrimitive>
                </ContextMenuItem>
                <ContextMenuSeparator />
                <ContextMenuItem asChild>
                    <ButtonPrimitive menuItem onClick={() => removeTab(tab)}>
                        <IconX /> Close tab <KeyboardShortcut command shift b />
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
            </ContextMenuContent>
        </ContextMenu>
    )
}
