import { router } from 'kea-router'
import { ReactNode } from 'react'

import { IconEllipsis } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuGroup, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { ListBox } from 'lib/ui/ListBox/ListBox'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'

import { NewTabTreeDataItem } from '../newTabSceneLogic'
import { convertToTreeDataItem } from './Results'

export interface ProjectFileBrowserProps {
    items: NewTabTreeDataItem[]
    parentPath: string | null
    currentPath: string
    onOpenFolder: (path: string, options?: { focusPath?: string | null }) => void
    search: string
    hasMore: boolean
    isLoading: boolean
    onLoadMore: () => void
}

function itemNameWithHighlight(item: NewTabTreeDataItem, search: string): ReactNode {
    if (!search) {
        return item.displayName || item.name
    }
    const highlightSource = typeof item.displayName === 'string' ? item.displayName : item.name
    return <SearchHighlightMultiple string={highlightSource || ''} substring={search} />
}

export function ProjectFileBrowser({
    items,
    parentPath,
    currentPath,
    onOpenFolder,
    search,
    hasMore,
    isLoading,
    onLoadMore,
}: ProjectFileBrowserProps): JSX.Element {
    const parentNavigationPath = parentPath ?? ''
    const hasParentButton = true

    return (
        <ListBox.Group groupId="project-file-browser" className="flex flex-col gap-1">
            {hasParentButton ? (
                <ButtonGroupPrimitive className="group w-full border-0">
                    <ListBox.Item asChild row={0} column={0} focusKey="project-browser-parent" index={0}>
                        <ButtonPrimitive
                            size="sm"
                            className="w-full justify-start"
                            onClick={() =>
                                onOpenFolder(parentNavigationPath, { focusPath: parentPath ? currentPath : null })
                            }
                        >
                            <span className="text-sm">..</span>
                        </ButtonPrimitive>
                    </ListBox.Item>
                </ButtonGroupPrimitive>
            ) : null}
            {items.map((item, index) => {
                const isFolder = item.record && (item.record as any).type === 'folder'
                const listIndex = hasParentButton ? index + 1 : index
                return (
                    <ButtonGroupPrimitive key={item.id} className="group w-full border-0">
                        <ContextMenu>
                            <ContextMenuTrigger asChild>
                                <ListBox.Item asChild row={listIndex} column={0} focusKey={item.id} index={listIndex}>
                                    <Link
                                        to={item.href || '#'}
                                        className="w-full"
                                        buttonProps={{
                                            size: 'sm',
                                            hasSideActionRight: true,
                                        }}
                                        onClick={(e) => {
                                            e.preventDefault()
                                            if (isFolder && item.record) {
                                                onOpenFolder((item.record as any).path || '')
                                            } else if (item.href) {
                                                router.actions.push(item.href)
                                            }
                                        }}
                                    >
                                        <span className="text-sm">{item.icon ?? item.name[0]}</span>
                                        <span className="flex min-w-0 items-center gap-2">
                                            <span className="text-sm truncate text-primary">
                                                {itemNameWithHighlight(item, search)}
                                            </span>
                                        </span>
                                    </Link>
                                </ListBox.Item>
                            </ContextMenuTrigger>
                            <ContextMenuContent loop className="max-w-[250px]">
                                <ContextMenuGroup>
                                    <MenuItems
                                        item={convertToTreeDataItem(item)}
                                        type="context"
                                        root="project://"
                                        onlyTree={false}
                                        showSelectMenuOption={false}
                                    />
                                </ContextMenuGroup>
                            </ContextMenuContent>
                        </ContextMenu>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <ButtonPrimitive
                                    size="xs"
                                    iconOnly
                                    isSideActionRight
                                    className="opacity-0 group-hover:opacity-100 group-has-[button[data-state=open]]:opacity-100 mt-px"
                                >
                                    <IconEllipsis className="size-3" />
                                </ButtonPrimitive>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                                <DropdownMenuGroup>
                                    <MenuItems
                                        item={convertToTreeDataItem(item)}
                                        type="dropdown"
                                        root="project://"
                                        onlyTree={false}
                                        showSelectMenuOption={false}
                                    />
                                </DropdownMenuGroup>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </ButtonGroupPrimitive>
                )
            })}
            {hasMore ? (
                <ListBox.Item
                    asChild
                    row={items.length + (hasParentButton ? 1 : 0)}
                    column={0}
                    focusKey="project-browser-load-more"
                    index={items.length + (hasParentButton ? 1 : 0)}
                >
                    <ButtonPrimitive
                        size="sm"
                        onClick={() => onLoadMore()}
                        disabled={isLoading}
                        className="w-full text-tertiary"
                    >
                        {isLoading ? 'Loading...' : 'Load more...'}
                    </ButtonPrimitive>
                </ListBox.Item>
            ) : null}
        </ListBox.Group>
    )
}
