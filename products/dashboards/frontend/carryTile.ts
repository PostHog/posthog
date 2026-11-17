// react-grid-layout's drag threshold, so a press that travels further was a drag.
const CLICK_TRAVEL_LIMIT_PX = 3
const KEEP_CLICK_SELECTOR = [
    'textarea',
    'select',
    'label',
    '[role="button"]',
    '[role="menuitem"]',
    '[role="textbox"]',
    '[contenteditable="true"]',
    '.ProseMirror',
    '.react-resizable-handle',
].join(',')

export interface TilePickUp {
    target: Element
    grid: Element
}

export interface TileCarry {
    cancel: () => void
}

interface CarryTileProps extends TilePickUp {
    clientX: number
    clientY: number
    held?: boolean
    onHeldRelease?: (event: MouseEvent) => void
    onDrop: () => void
    onCancel: () => void
}

function dispatchMouse(target: EventTarget, type: string, clientX: number, clientY: number, buttons: number): void {
    target.dispatchEvent(
        new MouseEvent(type, { bubbles: true, cancelable: true, view: window, clientX, clientY, button: 0, buttons })
    )
}

function swallowEvent(event: Event): void {
    event.preventDefault()
    event.stopPropagation()
}

export function travelledLikeClick(press: { x: number; y: number }, clientX: number, clientY: number): boolean {
    return Math.hypot(clientX - press.x, clientY - press.y) <= CLICK_TRAVEL_LIMIT_PX
}

export function getTilePickUp(
    event: MouseEvent,
    press: { x: number; y: number } | null,
    handleSelector: string,
    cancelSelector: string
): TilePickUp | null {
    if (!press || event.button !== 0 || event.detail > 1) {
        return null
    }
    if (!travelledLikeClick(press, event.clientX, event.clientY)) {
        return null
    }
    const target = event.target instanceof Element ? event.target : null
    const gridItem = target?.closest('.react-grid-item')
    const grid = gridItem?.parentElement
    const handle = target?.closest(handleSelector)
    if (!target || !gridItem || !grid || !handle || !gridItem.contains(handle)) {
        return null
    }
    if (target.closest(cancelSelector) || target.closest(KEEP_CLICK_SELECTOR)) {
        return null
    }
    return { target, grid }
}

export function carryTile({
    target,
    grid,
    clientX,
    clientY,
    held = false,
    onHeldRelease,
    onDrop,
    onCancel,
}: CarryTileProps): TileCarry {
    const gridRect = grid.getBoundingClientRect()
    const offsetX = clientX - gridRect.left
    const offsetY = clientY - gridRect.top
    let carrying = true
    let awaitingHeldRelease = held
    let pointerX = clientX
    let pointerY = clientY

    const stop = (): void => {
        carrying = false
        window.removeEventListener('mousedown', swallowLeftPress, { capture: true })
        window.removeEventListener('mouseup', drop, { capture: true })
        window.removeEventListener('keydown', cancelOnEscape, { capture: true })
        window.removeEventListener('mousemove', trackPointer, { capture: true })
        document.removeEventListener('scroll', followScroll, { capture: true })
    }

    function trackPointer(event: MouseEvent): void {
        pointerX = event.clientX
        pointerY = event.clientY
    }

    function followScroll(): void {
        dispatchMouse(document, 'mousemove', pointerX, pointerY, 1)
    }

    function swallowLeftPress(event: MouseEvent): void {
        if (event.button === 0) {
            swallowEvent(event)
        }
    }

    function drop(event: MouseEvent): void {
        if (event.button !== 0) {
            return
        }
        window.addEventListener('click', swallowEvent, { capture: true, once: true })
        window.setTimeout(() => window.removeEventListener('click', swallowEvent, { capture: true }), 0)
        if (awaitingHeldRelease) {
            // Letting go of the held press keeps the tile moving, so react-grid-layout must not see this release.
            awaitingHeldRelease = false
            swallowEvent(event)
            onHeldRelease?.(event)
            return
        }
        // This release has to reach react-grid-layout to end the drag. Only the click that follows is swallowed.
        stop()
        onDrop()
    }

    const cancel = (): void => {
        if (!carrying) {
            return
        }
        stop()
        // Called before the release, so the grid's drag stop handler already sees the move as canceled.
        onCancel()
        const rect = grid.getBoundingClientRect()
        const x = rect.left + offsetX
        const y = rect.top + offsetY
        dispatchMouse(document, 'mousemove', x, y, 1)
        dispatchMouse(document, 'mouseup', x, y, 0)
    }

    function cancelOnEscape(event: KeyboardEvent): void {
        if (event.key === 'Escape') {
            swallowEvent(event)
            cancel()
        }
    }

    if (!held) {
        dispatchMouse(target, 'mousedown', clientX, clientY, 1)
    }
    window.addEventListener('mousedown', swallowLeftPress, { capture: true })
    window.addEventListener('mouseup', drop, { capture: true })
    window.addEventListener('keydown', cancelOnEscape, { capture: true })
    window.addEventListener('mousemove', trackPointer, { capture: true, passive: true })
    // Scroll events do not bubble, so capture catches the scene's own scroll container too.
    document.addEventListener('scroll', followScroll, { capture: true, passive: true })

    return { cancel }
}
