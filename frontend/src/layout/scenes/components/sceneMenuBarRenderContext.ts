import { RefObject, createContext } from 'react'

interface MenubarRender {
    kind: 'menubar'
}

export interface FlatRender {
    kind: 'flat'
    inList: boolean
    destructiveFooter: HTMLElement | null
    openPopover: (id: string) => void
    getCaptureProperties: () => Record<string, unknown>
}

/**
 * A second, always-mounted pass over the scene's menu children. Only `SceneMenuBarPopover` renders here. The menu
 * list unmounts when it closes, so a popover opened from a menu row cannot live inside it.
 */
export interface PopoverHostRender {
    kind: 'popover-host'
    openPopoverId: string | null
    closePopover: () => void
    anchor: RefObject<HTMLButtonElement>
}

export type SceneMenuBarRender = MenubarRender | FlatRender | PopoverHostRender

export const SceneMenuBarRenderContext = createContext<SceneMenuBarRender>({ kind: 'menubar' })
