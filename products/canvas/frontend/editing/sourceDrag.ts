import { blockDefinition } from './blockLibrary/blockDefinitions'
import type { SourceDropTarget } from './blockLibrary/sourceEdits'
import { canvasEditorFrame, postToCanvasEditor } from './canvasEditorFrame'
import { SourceDragGhost, canvasSourceDragLogic } from './canvasSourceDragLogic'
import type { CanvasEditSelection } from './canvasSourceSnapshots'
import { libraryLabel } from './libraryCatalog'

// A drag starts in the host (a library item) or in the frame (a block on the canvas), and
// the pointer crosses between them, so the host drives it. It forwards the pointer into the
// frame, which answers with the drop target under it. Ported from PostHog Desktop's sourceDrag.

export type SourceDragSource = { kind: 'new'; blockType: string } | { kind: 'move'; selection: CanvasEditSelection }

export interface SourceDropHit {
    rev: number
    target: SourceDropTarget
}

const ACTIVATION_DISTANCE = 4
const MAX_TILT = 3
const TILT_GAIN = 0.3
const TILT_EASE = 0.18
const DROP_EXIT_MS = 140
const RETURN_EXIT_MS = 280

function prefersReducedMotion(): boolean {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function setGhost(ghost: SourceDragGhost | null): void {
    canvasSourceDragLogic.findMounted()?.actions.setGhost(ghost)
}

function leaveGhost(ghost: SourceDragGhost, duration: number): void {
    canvasSourceDragLogic.findMounted()?.actions.leaveGhost(ghost, duration)
}

export interface SourceDragController {
    move: (clientX: number, clientY: number) => void
    hit: (hit: SourceDropHit | null) => void
    end: (commit: boolean) => void
}

let active: SourceDragController | null = null

export function activeSourceDrag(): SourceDragController | null {
    return active
}

function hintFor(hit: SourceDropHit | null): string {
    if (!hit) {
        return 'Drop on the canvas'
    }
    if (hit.target.place === 'left' || hit.target.place === 'right') {
        return 'Place side by side'
    }
    if (hit.target.place === 'inside') {
        return 'Add at the end'
    }
    return 'Place here'
}

function isDataBlock(blockType: string | null): boolean {
    return !!blockType && blockDefinition(blockType)?.group === 'Data'
}

export function beginSourceDrag(options: {
    source: SourceDragSource
    startX: number
    startY: number
    onDrop: (source: SourceDragSource, hit: SourceDropHit) => void
    onClick?: () => void
}): void {
    active?.end(false)
    const { source } = options
    const blockType = source.kind === 'new' ? source.blockType : source.selection.blockType
    const label = libraryLabel(blockType, source.kind === 'move' ? source.selection.tag : undefined)
    let started = source.kind === 'move'
    let lastX = options.startX
    let tilt = 0
    let latestHit: SourceDropHit | null = null
    const coarse = isDataBlock(blockType)
    const reduceMotion = prefersReducedMotion()
    let lastGhost: SourceDragGhost | null = null
    const exclude =
        source.kind === 'move' && source.selection.source
            ? `${source.selection.source.file}|${source.selection.source.start}|${source.selection.source.end}`
            : null

    const render = (x: number, y: number): void => {
        const velocity = x - lastX
        lastX = x
        const wanted = Math.max(-MAX_TILT, Math.min(MAX_TILT, velocity * TILT_GAIN))
        tilt += (wanted - tilt) * TILT_EASE
        const ghost: SourceDragGhost = {
            label,
            blockType,
            x,
            y,
            tilt: reduceMotion ? 0 : tilt,
            hint: hintFor(latestHit),
            phase: 'drag',
        }
        lastGhost = ghost
        setGhost(ghost)
    }

    const forward = (x: number, y: number): void => {
        const rect = canvasEditorFrame()?.getBoundingClientRect()
        const inside = !!rect && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
        if (!rect || !inside) {
            latestHit = null
            postToCanvasEditor({ type: 'canvas-edit-drag-end' })
            return
        }
        postToCanvasEditor({ type: 'canvas-edit-drag-move', x: x - rect.left, y: y - rect.top, exclude, coarse })
    }

    const controller: SourceDragController = {
        move(x, y) {
            if (!started) {
                if (Math.hypot(x - options.startX, y - options.startY) < ACTIVATION_DISTANCE) {
                    return
                }
                started = true
            }
            render(x, y)
            forward(x, y)
        },
        hit(hit) {
            latestHit = hit
        },
        end(commit) {
            window.removeEventListener('pointermove', onMove, true)
            window.removeEventListener('pointerup', onUp, true)
            window.removeEventListener('pointercancel', onCancel, true)
            window.removeEventListener('blur', onCancel)
            window.removeEventListener('keydown', onKey, true)
            postToCanvasEditor({ type: 'canvas-edit-drag-end', final: true })
            active = null
            if (!started || !lastGhost) {
                setGhost(null)
                if (commit && !started) {
                    options.onClick?.()
                }
                return
            }
            if (commit && latestHit) {
                leaveGhost({ ...lastGhost, phase: 'drop' }, DROP_EXIT_MS)
                options.onDrop(source, latestHit)
                return
            }
            leaveGhost(
                { ...lastGhost, x: options.startX, y: options.startY, tilt: 0, phase: 'return' },
                reduceMotion ? DROP_EXIT_MS : RETURN_EXIT_MS
            )
        },
    }

    const onMove = (event: PointerEvent): void => controller.move(event.clientX, event.clientY)
    const onUp = (): void => controller.end(true)
    const onCancel = (): void => controller.end(false)
    const onKey = (event: KeyboardEvent): void => {
        if (event.key !== 'Escape') {
            return
        }
        event.preventDefault()
        event.stopPropagation()
        controller.end(false)
    }

    window.addEventListener('pointermove', onMove, true)
    window.addEventListener('pointerup', onUp, true)
    window.addEventListener('pointercancel', onCancel, true)
    window.addEventListener('blur', onCancel)
    window.addEventListener('keydown', onKey, true)
    active = controller
    if (started) {
        render(options.startX, options.startY)
    }
}
