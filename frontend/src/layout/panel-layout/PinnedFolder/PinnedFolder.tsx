import { useActions, useValues } from 'kea'

import { IconCheck, IconGear, IconPlusSmall } from '@posthog/icons'

import { ItemSelectModalButton } from 'lib/components/FileSystem/ItemSelectModal/ItemSelectModal'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { pinnedFolderLogic } from '~/layout/panel-layout/PinnedFolder/pinnedFolderLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { formatUrlAsName } from '~/layout/panel-layout/ProjectTree/utils'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

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
                    <IconGear className="text-secondary size-3" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                <DropdownMenuLabel>Choose pinned folder</DropdownMenuLabel>
                <DropdownMenuSeparator />
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
                        Products
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )

    return (
        <>
            {!isLayoutNavCollapsed &&
                (showDefaultHeader ? (
                    <div className="relative -mt-[3px] flex items-center justify-between pl-3 pr-1">
                        <div className="flex items-center gap-1">
                            <span className="text-tertiary text-xs font-semibold">{formatUrlAsName(pinnedFolder)}</span>
                        </div>
                        <div className="flex items-center gap-px">
                            {pinnedFolder === 'shortcuts://' ? (
                                <ItemSelectModalButton
                                    buttonProps={{
                                        iconOnly: true,
                                        tooltip: 'Add shortcut',
                                        tooltipPlacement: 'top',
                                        children: <IconPlusSmall className="text-tertiary size-4" />,
                                    }}
                                />
                            ) : null}
                            {configMenu}
                        </div>
                    </div>
                ) : (
                    <div className="absolute right-1 top-px z-10">{configMenu}</div>
                ))}
            <div className="group/colorful-product-icons colorful-product-icons-true mt-[-0.25rem] flex h-full flex-col">
                <ProjectTree root={pinnedFolder} onlyTree treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'} />
            </div>
        </>
    )
}
