import { useActions, useValues } from 'kea'
import React from 'react'

import { IconChevronLeft, IconChevronRight, IconCopy, IconExternal, IconPencil, IconX } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import { SceneTab } from 'scenes/sceneTypes'

import { sceneLogic } from '~/scenes/sceneLogic'

export function SceneTabContextMenu({ tab, children }: { tab: SceneTab; children: React.ReactElement }): JSX.Element {
    const { tabs } = useValues(sceneLogic)
    const { setTabs, removeTab, duplicateTab, renameTab } = useActions(sceneLogic)

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
                    <ButtonPrimitive menuItem onClick={() => duplicateTab(tab)}>
                        <IconCopy /> Duplicate tab
                    </ButtonPrimitive>
                </ContextMenuItem>
                <ContextMenuItem asChild>
                    <ButtonPrimitive menuItem onClick={() => renameTab(tab)}>
                        <IconPencil /> Rename tab
                    </ButtonPrimitive>
                </ContextMenuItem>
                <ContextMenuItem asChild>
                    <ButtonPrimitive menuItem onClick={openInNewWindow}>
                        <IconExternal /> Open in new window
                    </ButtonPrimitive>
                </ContextMenuItem>
                <ContextMenuItem asChild>
                    <ButtonPrimitive menuItem onClick={() => removeTab(tab)}>
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
            </ContextMenuContent>
        </ContextMenu>
    )
}
