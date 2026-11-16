import { ReactNode, useState } from 'react'

import { DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '@posthog/quill'

import { ActionsMenuRender, SceneMenuBarRenderContext } from './sceneMenuBarRenderContext'
import { COLLAPSED_ROWS_HIDDEN_CLASS, useCollapseMenuRows } from './useCollapseMenuRows'

type SceneActionsSubmenuProps = {
    trigger: ReactNode
    dataAttr?: string
    render: ActionsMenuRender
    onOpenChange?: (open: boolean) => void
    children: ReactNode
}

export function SceneActionsSubmenu({
    trigger,
    dataAttr,
    render,
    onOpenChange,
    children,
}: SceneActionsSubmenuProps): JSX.Element {
    const [content, setContent] = useState<HTMLDivElement | null>(null)
    useCollapseMenuRows(content)

    return (
        <DropdownMenuSub onOpenChange={onOpenChange}>
            <DropdownMenuSubTrigger data-attr={dataAttr}>{trigger}</DropdownMenuSubTrigger>
            <DropdownMenuSubContent ref={setContent} className={COLLAPSED_ROWS_HIDDEN_CLASS}>
                <SceneMenuBarRenderContext.Provider value={render}>{children}</SceneMenuBarRenderContext.Provider>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
