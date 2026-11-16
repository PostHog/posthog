import { ReactNode, RefObject, createContext } from 'react'

interface MenubarRender {
    kind: 'menubar'
}

export interface ActionsMenuRender {
    kind: 'actions-menu'
    level: 'top' | 'submenu' | 'kept'
    results: boolean
    destructiveOnly: boolean
    path: ReactNode[]
    nonEmptyMenus: ReadonlySet<string>
    openPopover: (id: string) => void
    getCaptureProperties: () => Record<string, unknown>
}

/**
 * A second, always-mounted pass over the scene's menu children. `SceneMenuBarPopover` renders its popover here,
 * because the menu list unmounts when it closes. Every other row renders a hidden probe, which tells the menu which
 * top-level menus have rows before any of them opens.
 */
export interface PopoverHostRender {
    kind: 'popover-host'
    openPopoverId: string | null
    closePopover: () => void
    anchor: RefObject<HTMLButtonElement>
}

export const MENU_PROBE_ATTRIBUTE = 'data-scene-menu-probe'
export const ROW_PROBE_ATTRIBUTE = 'data-scene-menu-probe-row'

export type SceneMenuBarRender = MenubarRender | ActionsMenuRender | PopoverHostRender

export const SceneMenuBarRenderContext = createContext<SceneMenuBarRender>({ kind: 'menubar' })
