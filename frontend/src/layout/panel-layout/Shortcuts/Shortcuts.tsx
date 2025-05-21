import { IconGear } from '@posthog/icons'
import { useValues } from 'kea'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { AddShortcutModal } from '~/layout/panel-layout/Shortcuts/AddShortcutModal'

export function Shortcuts(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    const [shortcutsPath, setShortcutsPath] = useState('products://')

    return (
        <>
            {!isLayoutNavCollapsed && (
                <div className="flex justify-between items-center pl-3 pr-1 relative">
                    <div className="flex items-center gap-1">
                        <span className="text-xs font-semibold text-quaternary">{shortcutsPath}</span>
                    </div>
                    <ButtonPrimitive
                        onClick={() => {
                            const path = window.prompt('Path to show', shortcutsPath)
                            path && setShortcutsPath(path)
                        }}
                        iconOnly
                        tooltip="Add shortcut"
                        tooltipPlacement="right"
                    >
                        <IconGear className="size-3 text-secondary" />
                    </ButtonPrimitive>
                </div>
            )}

            {isLayoutNavCollapsed && (
                <ButtonPrimitive
                    onClick={() => {
                        const path = window.prompt('Path to show', shortcutsPath)
                        path && setShortcutsPath(path)
                    }}
                    iconOnly
                    tooltip="Change path"
                    tooltipPlacement="right"
                >
                    <IconGear className="size-3 text-secondary" />
                </ButtonPrimitive>
            )}

            <div className="mt-[-0.25rem] h-full">
                {/* TODO: move this tree into popover if isLayoutNavCollapsed is true */}
                <ProjectTree root={shortcutsPath} logicKey={shortcutsPath} onlyTree />
            </div>
            <AddShortcutModal />
        </>
    )
}
