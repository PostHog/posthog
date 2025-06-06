import { IconCheck, IconGear } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { FolderSelect } from 'lib/components/FolderSelect/FolderSelect'
import { IconBlank } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { pinnedFolderLogic } from '~/layout/panel-layout/PinnedFolder/pinnedFolderLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { formatUrlAsName } from '~/layout/panel-layout/ProjectTree/utils'

export function PinnedFolder(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { modalVisible, pinnedFolder, selectedFolder } = useValues(pinnedFolderLogic)
    const { hideModal, showModal, setPinnedFolder, setSelectedFolder } = useActions(pinnedFolderLogic)

    const showDefaultHeader = pinnedFolder !== 'products://' && pinnedFolder !== 'data://'

    const configMenu = (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive iconOnly data-attr="tree-navbar-pinned-folder-change-button">
                    <IconGear className="size-3 text-secondary" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
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
                        Products
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
                <DropdownMenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        showModal()
                    }}
                    data-attr="tree-item-menu-open-link-button"
                >
                    <ButtonPrimitive menuItem>
                        {pinnedFolder && pinnedFolder !== 'products://' && pinnedFolder !== 'shortcuts://' ? (
                            <IconCheck />
                        ) : (
                            <IconBlank />
                        )}
                        Custom...
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )

    return (
        <>
            {!isLayoutNavCollapsed &&
                (showDefaultHeader ? (
                    <div className="flex justify-between items-center pl-3 pr-1 relative">
                        <div className="flex items-center gap-1">
                            <span className="text-xs font-semibold text-quaternary">
                                {formatUrlAsName(pinnedFolder)}
                            </span>
                        </div>
                        {configMenu}
                    </div>
                ) : (
                    <div className="absolute right-1 z-10">{configMenu}</div>
                ))}
            <div className="flex flex-col mt-[-0.25rem] h-full group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root={pinnedFolder} onlyTree treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'} />
            </div>
            {modalVisible ? (
                <LemonModal
                    onClose={hideModal}
                    isOpen
                    title="Change pinned folder"
                    footer={
                        typeof selectedFolder === 'string' ? (
                            <>
                                <div className="flex-1" />
                                <LemonButton
                                    type="primary"
                                    onClick={() => setPinnedFolder(selectedFolder)}
                                    data-attr="tree-navbar-pinned-folder-change-select-button"
                                >
                                    Select {formatUrlAsName(selectedFolder, 'Project root')}
                                </LemonButton>
                            </>
                        ) : null
                    }
                >
                    <div className="w-192 max-w-full">
                        <FolderSelect
                            value={selectedFolder}
                            onChange={setSelectedFolder}
                            includeProtocol
                            className="h-[60vh] min-h-[200px]"
                        />
                    </div>
                </LemonModal>
            ) : null}
        </>
    )
}
