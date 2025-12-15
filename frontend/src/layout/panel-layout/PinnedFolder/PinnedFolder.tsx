import { useActions, useValues } from 'kea'

import { IconCheck, IconGear, IconPencil, IconPlusSmall } from '@posthog/icons'

import { ItemSelectModalButton } from 'lib/components/FileSystem/ItemSelectModal/ItemSelectModal'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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

import { EditCustomProductsModal } from '~/layout/panel-layout/PinnedFolder/EditCustomProductsModal'
import { pinnedFolderLogic } from '~/layout/panel-layout/PinnedFolder/pinnedFolderLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { formatUrlAsName } from '~/layout/panel-layout/ProjectTree/utils'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { editCustomProductsModalLogic } from './editCustomProductsModalLogic'

const SelectedIcon = ({ checked }: { checked: boolean }): JSX.Element => {
    return checked ? <IconCheck /> : <IconBlank />
}

export function PinnedFolder(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { pinnedFolder } = useValues(pinnedFolderLogic)
    const { setPinnedFolder } = useActions(pinnedFolderLogic)
    const { openModal: openEditCustomProductsModal } = useActions(editCustomProductsModalLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const showDefaultHeader = !['products://', 'data://', 'custom-products://'].includes(pinnedFolder)

    const isCustomProductsSidebarEnabled = featureFlags[FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR] === 'test'
    const CustomProductsIcon = isCustomProductsSidebarEnabled ? IconGear : IconPencil

    const configMenu = (
        <>
            {pinnedFolder === 'shortcuts://' ? (
                <ItemSelectModalButton
                    buttonProps={{
                        iconOnly: true,
                        size: 'xs',
                        tooltip: 'Add shortcut',
                        tooltipPlacement: 'top',
                        children: <IconPlusSmall className="size-4 text-tertiary" />,
                    }}
                />
            ) : null}
            {pinnedFolder === 'custom-products://' ? (
                <ButtonPrimitive
                    iconOnly
                    tooltip="Edit my sidebar apps"
                    tooltipPlacement="top"
                    onClick={openEditCustomProductsModal}
                    size="xs"
                >
                    <CustomProductsIcon className="size-3 text-secondary" />
                </ButtonPrimitive>
            ) : null}

            {!isCustomProductsSidebarEnabled && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive
                            iconOnly
                            data-attr="tree-navbar-pinned-folder-change-button"
                            tooltip="Change sidebar mode"
                            tooltipPlacement="top"
                            size="xs"
                        >
                            <IconGear className="size-3 text-secondary" />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Choose sidebar mode</DropdownMenuLabel>
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
                                    All apps&nbsp;
                                    <SelectedIcon checked={!pinnedFolder || pinnedFolder === 'products://'} />
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
                                    Shortcuts only&nbsp;
                                    <SelectedIcon checked={pinnedFolder === 'shortcuts://'} />
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </>
    )

    return (
        <>
            {!isLayoutNavCollapsed &&
                (showDefaultHeader ? (
                    <div className="flex justify-between items-center pl-3 pr-1 -mt-[3px] relative">
                        <div className="flex items-center gap-1">
                            <span className="text-xs font-semibold text-tertiary">{formatUrlAsName(pinnedFolder)}</span>
                        </div>
                        <div className="flex items-center gap-px">{configMenu}</div>
                    </div>
                ) : (
                    <div className="absolute right-1 z-10 top-px">{configMenu}</div>
                ))}
            <div className="flex flex-col mt-[-0.5rem] h-full group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root={pinnedFolder} onlyTree treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'} />
            </div>
            <EditCustomProductsModal />
        </>
    )
}
