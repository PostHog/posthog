import { Tooltip } from '@base-ui/react/tooltip'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconClock } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { MenuSeparator } from 'lib/ui/Menus/Menus'
import { tooltipHandle } from 'lib/ui/Tooltip/GlobalTooltip'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { recentItemsMenuLogic } from './recentItemsMenuLogic'

const getItemName = (item: FileSystemEntry): string => {
    const pathSplit = splitPath(item.path)
    const lastPart = pathSplit.pop()
    return unescapePath(lastPart ?? item.path)
}

export function RecentItemsMenu(): JSX.Element {
    const { recentItems, recentItemsLoading } = useValues(recentItemsMenuLogic)
    const { loadRecentItems } = useActions(recentItemsMenuLogic)
    const [isOpen, setIsOpen] = useState(false)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    const handleOpenChange = (open: boolean): void => {
        setIsOpen(open)
        if (open) {
            loadRecentItems({})
        }
    }

    useAppShortcut({
        name: 'recent-items-menu',
        keybind: [keyBinds.recentItems],
        intent: 'Open recent items menu',
        interaction: 'function',
        callback: () => setIsOpen(true),
    })

    return (
        <DropdownMenu open={isOpen} onOpenChange={handleOpenChange}>
            <Tooltip.Trigger
                payload={{
                    title: 'Recent items',
                    keyboardShortcut: [keyBinds.recentItems],
                    side: isLayoutNavCollapsed ? 'right' : 'bottom',
                }}
                handle={tooltipHandle}
                render={
                    <div>
                        <DropdownMenuTrigger asChild>
                            <ButtonPrimitive iconOnly size="sm" data-attr="recent-items-menu-trigger">
                                <IconClock className="size-4 text-tertiary" />
                            </ButtonPrimitive>
                        </DropdownMenuTrigger>
                    </div>
                }
            />
            <DropdownMenuContent align="start" side="bottom" className="min-w-[200px] max-w-[300px]">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Recent items</DropdownMenuLabel>
                    <MenuSeparator />
                    {recentItemsLoading ? (
                        <DropdownMenuItem disabled>
                            <ButtonPrimitive menuItem>
                                <Spinner className="size-4" />
                                <span className="ml-2">Loading...</span>
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    ) : recentItems.length === 0 ? (
                        <DropdownMenuItem disabled>
                            <ButtonPrimitive menuItem>No recent items</ButtonPrimitive>
                        </DropdownMenuItem>
                    ) : (
                        recentItems.map((item: FileSystemEntry) => (
                            <DropdownMenuItem key={item.id} asChild>
                                <Link
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                    to={item.href}
                                    data-attr={`recent-item-${item.id}`}
                                >
                                    {iconForType(item.type as FileSystemIconType)}
                                    <span className="ml-2 truncate">{getItemName(item)}</span>
                                </Link>
                            </DropdownMenuItem>
                        ))
                    )}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
