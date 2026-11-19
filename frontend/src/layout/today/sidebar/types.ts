import type { KeyboardEvent, PointerEvent } from 'react'

export interface SidebarSectionResizer {
    onPointerDown: (event: PointerEvent<HTMLElement>) => void
    onPointerMove: (event: PointerEvent<HTMLElement>) => void
    onPointerUp: (event: PointerEvent<HTMLElement>) => void
    onPointerCancel: () => void
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => void
    onDoubleClick: () => void
}
