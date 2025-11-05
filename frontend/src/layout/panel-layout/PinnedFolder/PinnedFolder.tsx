import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconGear, IconPlusSmall } from '@posthog/icons'

import { draggableLinkLogic } from 'lib/components/DraggableLink/draggableLinkLogic'
import { ItemSelectModalButton } from 'lib/components/FileSystem/ItemSelectModal/ItemSelectModal'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { pinnedFolderLogic } from '~/layout/panel-layout/PinnedFolder/pinnedFolderLogic'
import { shortcutDropLogic } from '~/layout/panel-layout/PinnedFolder/shortcutDropLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { formatUrlAsName } from '~/layout/panel-layout/ProjectTree/utils'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

function ShortcutDropZone({ children }: { children: React.ReactNode }): JSX.Element {
    const { dropMode } = useValues(draggableLinkLogic)
    const { handleShortcutDrop } = useActions(shortcutDropLogic)
    const [isDragOver, setIsDragOver] = useState(false)

    const handleDragOver = (e: React.DragEvent): void => {
        e.preventDefault()
        setIsDragOver(true)
    }

    const handleDragLeave = (e: React.DragEvent): void => {
        e.preventDefault()
        setIsDragOver(false)
    }

    const handleDrop = (e: React.DragEvent): void => {
        e.preventDefault()
        setIsDragOver(false)

        const href = e.dataTransfer.getData('text/href')
        const title = e.dataTransfer.getData('text/title')
        const iconType = e.dataTransfer.getData('text/iconType')

        if (href) {
            handleShortcutDrop(href, title, iconType)
        }
    }

    const showDropZone = dropMode && isDragOver

    return (
        <div
            className={`relative h-full flex-1 ${showDropZone ? 'bg-accent/10 outline-2 outline-dashed outline-accent' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
        >
            {children}
            {showDropZone && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-50">
                    <div className="bg-white/90 backdrop-blur-sm px-3 py-2 rounded-md border text-sm font-medium">
                        Drop to add shortcut
                    </div>
                </div>
            )}
        </div>
    )
}

export function PinnedFolder(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { pinnedFolder } = useValues(pinnedFolderLogic)
    const { setPinnedFolder } = useActions(pinnedFolderLogic)
    const showDefaultHeader = pinnedFolder !== 'products://' && pinnedFolder !== 'data://'

    const configMenu = (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive
                    iconOnly
                    data-attr="tree-navbar-pinned-folder-change-button"
                    tooltip="Change pinned folder"
                    tooltipPlacement="top"
                >
                    <IconGear className="size-3 text-secondary" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Choose pinned folder</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            setPinnedFolder('products://')
                        }}
                        data-attr="tree-item-menu-open-link-button"
                    >
                        <ButtonPrimitive menuItem>
                            {!pinnedFolder || pinnedFolder === 'products://' ? <IconCheck /> : <IconBlank />}
                            Apps
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            setPinnedFolder('shortcuts://')
                        }}
                        data-attr="tree-item-menu-open-link-button"
                    >
                        <ButtonPrimitive menuItem>
                            {pinnedFolder === 'shortcuts://' ? <IconCheck /> : <IconBlank />}
                            Shortcuts
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )

    const content = (
        <>
            {!isLayoutNavCollapsed &&
                (showDefaultHeader ? (
                    <div className="flex justify-between items-center pl-3 pr-1 -mt-[3px] relative">
                        <div className="flex items-center gap-1">
                            <span className="text-xs font-semibold text-tertiary">{formatUrlAsName(pinnedFolder)}</span>
                        </div>
                        <div className="flex items-center gap-px">
                            {pinnedFolder === 'shortcuts://' ? (
                                <ItemSelectModalButton
                                    buttonProps={{
                                        iconOnly: true,
                                        tooltip: 'Add shortcut',
                                        tooltipPlacement: 'top',
                                        children: <IconPlusSmall className="size-4 text-tertiary" />,
                                    }}
                                />
                            ) : null}
                            {configMenu}
                        </div>
                    </div>
                ) : (
                    <div className="absolute right-1 z-10 top-px">{configMenu}</div>
                ))}
            <div className="flex flex-col mt-[-0.25rem] h-full group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root={pinnedFolder} onlyTree treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'} />
            </div>
        </>
    )

    return pinnedFolder === 'shortcuts://' ? <ShortcutDropZone>{content}</ShortcutDropZone> : content
}
