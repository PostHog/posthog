import { router } from 'kea-router'
import { Fragment, MouseEvent } from 'react'

import {
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import { newInternalTab } from 'lib/utils/newInternalTab'

import type { SchemaItemAction } from './schemaItemActions'

function labelOf(action: SchemaItemAction): string {
    // The Lemon menu writes "+ New folder"; quill menus don't put symbols in labels.
    const label = action.label.replace(/^\+ /, '')
    return action.kind === 'item' && action.opensFloatingUi ? `${label}…` : label
}

/** A row inside the tree must not also trigger the tree row's own click, which selects or opens the item. */
function navigate(event: MouseEvent, href: string, newTab: boolean): void {
    event.stopPropagation()
    // Quill rows navigate in onClick rather than through a link, so a modifier click opens a new tab here.
    if (newTab || event.metaKey || event.ctrlKey) {
        newInternalTab(href)
    } else {
        router.actions.push(href)
    }
}

export function QuillSchemaItemMenuItems({
    groups,
    type,
}: {
    groups: SchemaItemAction[][]
    type: 'context' | 'dropdown'
}): JSX.Element {
    const isContext = type === 'context'
    const MenuGroup = isContext ? ContextMenuGroup : DropdownMenuGroup
    const MenuSeparator = isContext ? ContextMenuSeparator : DropdownMenuSeparator
    const MenuSub = isContext ? ContextMenuSub : DropdownMenuSub
    const MenuSubTrigger = isContext ? ContextMenuSubTrigger : DropdownMenuSubTrigger
    const MenuSubContent = isContext ? ContextMenuSubContent : DropdownMenuSubContent

    const renderItem = (
        key: string,
        label: string,
        onClick: (event: MouseEvent) => void,
        options: { disabledReason?: string | null; destructive?: boolean; dataAttr?: string }
    ): JSX.Element => {
        const variant = options.destructive ? 'destructive' : 'default'
        const MenuItem = isContext ? ContextMenuItem : DropdownMenuItem
        return (
            <MenuItem
                key={key}
                variant={variant}
                disabledReason={options.disabledReason || undefined}
                onClick={onClick}
                data-attr={options.dataAttr}
            >
                {label}
            </MenuItem>
        )
    }

    const renderAction = (action: SchemaItemAction): JSX.Element => {
        switch (action.kind) {
            case 'item':
                return renderItem(
                    action.key,
                    labelOf(action),
                    (event) => {
                        event.stopPropagation()
                        action.onSelect()
                    },
                    action
                )
            case 'link':
                return renderItem(
                    action.key,
                    labelOf(action),
                    (event) => {
                        action.onSelect?.()
                        navigate(event, action.href, !!action.newTab)
                    },
                    action
                )
            case 'open':
                return renderItem(
                    action.key,
                    labelOf(action),
                    (event) => navigate(event, action.href, !action.openInPlace),
                    action
                )
            case 'submenu':
                return (
                    <MenuSub key={action.key}>
                        <MenuSubTrigger data-attr={action.dataAttr}>{action.label}</MenuSubTrigger>
                        <MenuSubContent>{action.items.map(renderAction)}</MenuSubContent>
                    </MenuSub>
                )
        }
    }

    return (
        <>
            {groups.map((group, index) => (
                <Fragment key={group[0]?.key ?? index}>
                    {index > 0 ? <MenuSeparator /> : null}
                    <MenuGroup>{group.map(renderAction)}</MenuGroup>
                </Fragment>
            ))}
        </>
    )
}
