import { router } from 'kea-router'
import { ReactNode, useEffect, useMemo, useRef } from 'react'

import { IconArrowRightDown, IconEllipsis, IconFolder } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuGroup, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { ListBox, ListBoxGroupHandle } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'

import { NewTabTreeDataItem } from '../newTabSceneLogic'
import { convertToTreeDataItem } from './Results'

export interface ProjectFileBrowserProps {
    items: NewTabTreeDataItem[]
    parentPath: string | null
    currentPath: string
    onOpenFolder: (path: string | null, options?: { focusPath?: string | null }) => void
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
    const hasParentButton = parentPath !== null
    const trimmedSearch = useMemo(() => search.trim(), [search])
    const isFiltering = trimmedSearch.length > 0
    const parentMatchesSearch = trimmedSearch === '.' || trimmedSearch === '..'
    const showParentButton = hasParentButton && (!isFiltering || parentMatchesSearch)
    const groupRef = useRef<ListBoxGroupHandle | null>(null)

    useEffect(() => {
        if (isFiltering) {
            const targetIndex = parentMatchesSearch ? 0 : showParentButton ? 1 : 0
            if (parentMatchesSearch || items.length > 0) {
                groupRef.current?.resumeFocus(targetIndex)
            }
        }
    }, [isFiltering, items, parentMatchesSearch, showParentButton])

    const handleParentClick = (): void => {
        if (!currentPath) {
            onOpenFolder(null)
            return
        }

        onOpenFolder(parentNavigationPath, { focusPath: currentPath })
    }

    return (
        <ListBox.Group ref={groupRef} groupId="project-file-browser">
            <div className="flex flex-col gap-1">
                {showParentButton ? (
                    <ButtonGroupPrimitive className="group w-full border-0">
                        <ListBox.Item asChild row={0} column={0} focusKey="project-browser-parent" index={0}>
                            <ButtonPrimitive
                                size="sm"
                                className="w-full justify-start gap-2"
                                onClick={handleParentClick}
                            >
                                <span className="flex size-5 shrink-0 items-center justify-center text-muted ml-[-4px]">
                                    <IconArrowRightDown className="size-4 rotate-180" />
                                </span>
                                <span className="text-sm">..</span>
                            </ButtonPrimitive>
                        </ListBox.Item>
                    </ButtonGroupPrimitive>
                ) : null}
                {items.map((item, index) => {
                    const isFolder = item.record && (item.record as any).type === 'folder'
                    const listIndex = showParentButton ? index + 1 : index
                    const iconContent = isFolder ? <IconFolder className="size-4" /> : (item.icon ?? item.name[0])
                    return (
                        <ButtonGroupPrimitive key={item.id} className="group w-full border-0">
                            <ContextMenu>
                                <ContextMenuTrigger asChild>
                                    <ListBox.Item
                                        asChild
                                        row={listIndex}
                                        column={0}
                                        focusKey={item.id}
                                        index={listIndex}
                                    >
                                        <Link
                                            to={item.href || '#'}
                                            className="w-full"
                                            buttonProps={{
                                                size: 'sm',
                                                hasSideActionRight: true,
                                                className: cn(
                                                    'w-full',
                                                    isFiltering && 'data-[focused=true]:border-accent'
                                                ),
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
                                            <span className="flex size-5 shrink-0 items-center justify-center text-muted">
                                                {typeof iconContent === 'string' ? (
                                                    <span className="text-sm font-medium">{iconContent}</span>
                                                ) : (
                                                    iconContent
                                                )}
                                            </span>
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
                        row={items.length + (showParentButton ? 1 : 0)}
                        column={0}
                        focusKey="project-browser-load-more"
                        index={items.length + (showParentButton ? 1 : 0)}
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
            </div>
        </ListBox.Group>
    )
}
