const DRAG_THRESHOLD = 4
const EDGE = 8
const PANEL_HALF_WIDTH = 178
const MAX_TILT = 16
const TILT_PER_SPEED = 22
const STIFFNESS = 0.08
const DAMPING = 0.82
const VELOCITY_DECAY = 0.88
const MAX_STRETCH = 0.12
const LANDING_MS = 700

const clamp = (value: number, min: number, max: number): number => Math.min(Math.max(value, min), max)

interface LauncherDragOptions {
    origin: number
    onDragStart: () => void
    onDrop: (x: number) => void
}

export function startLauncherDrag(
    event: React.PointerEvent<HTMLElement>,
    { origin, onDragStart, onDrop }: LauncherDragOptions
): void {
    const handle = event.currentTarget
    const host = handle.parentElement?.getBoundingClientRect()
    if (event.button !== 0 || !host) {
        return
    }
    const rect = handle.getBoundingClientRect()
    const restCenter = rect.left + rect.width / 2 - origin
    const minX = Math.max(host.left + rect.width / 2 + EDGE, PANEL_HALF_WIDTH) - restCenter
    const maxX = Math.min(host.right - rect.width / 2 - EDGE, window.innerWidth - PANEL_HALF_WIDTH) - restCenter
    const minY = EDGE - rect.top
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const start = { x: event.clientX, y: event.clientY }
    const position = { x: origin, y: 0 }
    let last = { x: event.clientX, y: event.clientY, t: event.timeStamp }
    const velocity = { x: 0, y: 0 }
    const tilt = { angle: 0, speed: 0 }
    let dragging = false
    let released = false
    let frame = 0

    const paint = (): void => {
        velocity.x *= VELOCITY_DECAY
        velocity.y *= VELOCITY_DECAY
        const target = released ? 0 : clamp(velocity.x * TILT_PER_SPEED, -MAX_TILT, MAX_TILT)
        tilt.speed = (tilt.speed + (target - tilt.angle) * STIFFNESS) * DAMPING
        tilt.angle += tilt.speed
        const speed = released ? 0 : Math.hypot(velocity.x, velocity.y)
        const stretch = Math.min(speed * 0.1, MAX_STRETCH)
        const across = speed ? Math.abs(velocity.x) / speed : 1
        const along = 1 - across
        if (!released) {
            handle.style.translate = `${position.x}px ${position.y}px`
        }
        handle.style.setProperty('--launcher-tilt', `${tilt.angle.toFixed(2)}deg`)
        handle.style.setProperty('--launcher-sx', (1 + stretch * across - stretch * 0.6 * along).toFixed(3))
        handle.style.setProperty('--launcher-sy', (1 + stretch * along - stretch * 0.6 * across).toFixed(3))
        handle.style.setProperty('--launcher-drag-look-x', `${clamp(velocity.x * 4, -2, 2).toFixed(2)}px`)
        handle.style.setProperty('--launcher-drag-look-y', `${clamp(velocity.y * 3, -1.5, 1.5).toFixed(2)}px`)
        if (released && Math.abs(tilt.angle) < 0.05 && Math.abs(tilt.speed) < 0.05) {
            for (const name of ['--launcher-tilt', '--launcher-sx', '--launcher-sy']) {
                handle.style.removeProperty(name)
            }
            frame = 0
            return
        }
        frame = requestAnimationFrame(paint)
    }

    const land = (): void => {
        handle.dataset.landing = ''
        window.setTimeout(() => delete handle.dataset.landing, LANDING_MS)
    }

    const move = (moveEvent: PointerEvent): void => {
        const dx = moveEvent.clientX - start.x
        const dy = moveEvent.clientY - start.y
        if (!dragging) {
            if (Math.hypot(dx, dy) < DRAG_THRESHOLD) {
                return
            }
            dragging = true
            delete handle.dataset.landing
            handle.dataset.dragging = ''
            onDragStart()
            if (!still) {
                frame = requestAnimationFrame(paint)
            }
        }
        const dt = Math.max(moveEvent.timeStamp - last.t, 1)
        velocity.x = velocity.x * 0.5 + ((moveEvent.clientX - last.x) / dt) * 0.5
        velocity.y = velocity.y * 0.5 + ((moveEvent.clientY - last.y) / dt) * 0.5
        last = { x: moveEvent.clientX, y: moveEvent.clientY, t: moveEvent.timeStamp }
        position.x = clamp(origin + dx, minX, maxX)
        position.y = clamp(dy, minY, 0)
        if (still) {
            handle.style.translate = `${position.x}px ${position.y}px`
        }
    }

    const end = (): void => {
        handle.removeEventListener('pointermove', move)
        handle.removeEventListener('pointerup', end)
        handle.removeEventListener('pointercancel', end)
        if (!dragging) {
            return
        }
        released = true
        delete handle.dataset.dragging
        handle.style.translate = `${position.x}px 0px`
        const height = -position.y
        if (still) {
            cancelAnimationFrame(frame)
        } else if (height > 4) {
            const fall = handle.animate(
                [{ translate: `${position.x}px ${position.y}px` }, { translate: `${position.x}px 0px` }],
                { duration: clamp(Math.sqrt(height) * 26, 160, 520), easing: 'cubic-bezier(0.55, 0, 1, 0.45)' }
            )
            fall.onfinish = land
        } else {
            land()
        }
        onDrop(position.x)
    }

    handle.setPointerCapture(event.pointerId)
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', end)
    handle.addEventListener('pointercancel', end)
}
