import { useActions, useValues } from 'kea'
import { motion, useReducedMotion } from 'motion/react'
import { PointerEvent, useEffect, useRef, useState } from 'react'

import { IconCollapse45Chevrons, IconExpand45Chevrons, IconMinus, IconX } from '@posthog/icons'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'

import { osFrameName, osFrameSrc } from '../bridge/osFrame'
import { OsBounds, OsPoint, OsResizeEdge, OsSnapZone, resizeBounds, snapZoneAt } from './osWindowGeometry'
import { OS_WINDOW_SHORTCUT_KEYS, OsWindowCommand } from './osWindowShortcuts'
import { OsWindowState, osWindowsLogic } from './osWindowsLogic'
import { watchOsWindowFrame } from './watchOsWindowFrame'

const DRAG_THRESHOLD = 4

const RESIZE_HANDLES: { edge: OsResizeEdge; className: string }[] = [
    { edge: 'left', className: 'left-0 top-0 bottom-4 w-1.5 cursor-ew-resize' },
    { edge: 'right', className: 'right-0 top-0 bottom-4 w-1.5 cursor-ew-resize' },
    { edge: 'bottom', className: 'bottom-0 left-4 right-4 h-1.5 cursor-ns-resize' },
    { edge: 'bottom-left', className: 'bottom-0 left-0 size-4 cursor-nesw-resize' },
    { edge: 'bottom-right', className: 'bottom-0 right-0 size-4 cursor-nwse-resize' },
]

interface Gesture {
    kind: 'move' | OsResizeEdge
    pointerId: number
    start: OsPoint
    startBounds: OsBounds
    moved: boolean
    zone: OsSnapZone | null
    bounds: OsBounds
}

export interface OsWindowProps {
    window: OsWindowState
    focused: boolean
    desktopElement: HTMLElement | null
    /** True while any window is dragged or resized, so no frame swallows the pointer. */
    interacting: boolean
    onInteractionChange: (interacting: boolean) => void
    onSnapPreview: (zone: OsSnapZone | null) => void
}

function ShortcutHint({ label, command }: { label: string; command: OsWindowCommand }): JSX.Element {
    const keys = Object.fromEntries(OS_WINDOW_SHORTCUT_KEYS[command].map((key) => [key, true]))
    return (
        <span className="flex items-center gap-1">
            <span>{label}</span>
            <KeyboardShortcut {...keys} />
        </span>
    )
}

export function OsWindow({
    window: win,
    focused,
    desktopElement,
    interacting,
    onInteractionChange,
    onSnapPreview,
}: OsWindowProps): JSX.Element {
    const { desktop, zoomOrigins } = useValues(osWindowsLogic)
    const {
        focusWindow,
        closeWindow,
        minimizeWindow,
        maximizeWindow,
        unmaximizeWindow,
        snapWindow,
        setWindowBounds,
        windowNavigated,
    } = useActions(osWindowsLogic)
    const reduceMotion = useReducedMotion()
    const [liveBounds, setLiveBounds] = useState<OsBounds | null>(null)
    const gesture = useRef<Gesture | null>(null)
    const stopWatchingFrame = useRef<(() => void) | null>(null)
    // The frame loads its first path once. Later paths come from the frame itself, and changing `src` would reload it.
    const [src] = useState(() => osFrameSrc({ pathname: win.path, search: '', hash: '' }, window.location.origin))
    const [zoomOrigin] = useState(() => zoomOrigins[win.id] ?? null)

    useEffect(() => () => stopWatchingFrame.current?.(), [])

    // A shortcut can maximize, minimize or close a window mid-gesture, and its handles then never see the
    // pointer come up. Without this, every frame would keep ignoring the pointer.
    useEffect(
        () => () => {
            if (gesture.current?.moved) {
                onInteractionChange(false)
                onSnapPreview(null)
            }
            gesture.current = null
            setLiveBounds(null)
        },
        [win.maximized, win.minimized, onInteractionChange, onSnapPreview]
    )

    const bounds = liveBounds ?? win.bounds
    const toggleMaximize = (): void => (win.maximized ? unmaximizeWindow(win.id) : maximizeWindow(win.id))

    const toDesktop = (event: PointerEvent): OsPoint => {
        const rect = desktopElement?.getBoundingClientRect()
        return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) }
    }

    const startGesture = (kind: Gesture['kind'], event: PointerEvent<HTMLElement>): void => {
        if (event.button !== 0 || gesture.current) {
            return
        }
        event.currentTarget.setPointerCapture(event.pointerId)
        gesture.current = {
            kind,
            pointerId: event.pointerId,
            start: toDesktop(event),
            startBounds: win.bounds,
            moved: false,
            zone: null,
            bounds: win.bounds,
        }
        if (!focused) {
            focusWindow(win.id)
        }
    }

    const moveGesture = (event: PointerEvent<HTMLElement>): void => {
        const current = gesture.current
        if (!current || current.pointerId !== event.pointerId) {
            return
        }
        const pointer = toDesktop(event)
        const delta = { x: pointer.x - current.start.x, y: pointer.y - current.start.y }
        if (!current.moved) {
            if (Math.abs(delta.x) + Math.abs(delta.y) < DRAG_THRESHOLD) {
                return
            }
            current.moved = true
            onInteractionChange(true)
            if (current.kind === 'move' && win.restoreBounds) {
                // Dragging a maximized or snapped window takes it back to its old size under the pointer.
                const { width, height } = win.restoreBounds
                current.startBounds = { width, height, x: pointer.x - width / 2, y: 0 }
                current.start = pointer
                delta.x = 0
                delta.y = 0
            }
        }
        if (current.kind === 'move') {
            current.bounds = {
                ...current.startBounds,
                x: current.startBounds.x + delta.x,
                y: Math.max(0, current.startBounds.y + delta.y),
            }
            const zone = snapZoneAt(pointer, desktop)
            if (zone !== current.zone) {
                current.zone = zone
                onSnapPreview(zone)
            }
        } else {
            current.bounds = resizeBounds(current.startBounds, current.kind, delta)
        }
        setLiveBounds(current.bounds)
    }

    const endGesture = (event: PointerEvent<HTMLElement>): void => {
        const current = gesture.current
        if (!current || current.pointerId !== event.pointerId) {
            return
        }
        gesture.current = null
        if (current.moved) {
            onInteractionChange(false)
            onSnapPreview(null)
        }
        if (current.moved && event.type === 'pointerup') {
            if (current.zone === 'maximize') {
                maximizeWindow(win.id)
            } else if (current.zone) {
                snapWindow(win.id, current.zone)
            } else {
                setWindowBounds(win.id, current.bounds)
            }
        }
        setLiveBounds(null)
    }

    const gestureHandlers = {
        onPointerMove: moveGesture,
        onPointerUp: endGesture,
        onPointerCancel: endGesture,
        onLostPointerCapture: endGesture,
    }

    const onFrameLoad = (frame: HTMLIFrameElement): void => {
        stopWatchingFrame.current?.()
        const stopWatching = watchOsWindowFrame(frame, ({ path, title, traversed }) => {
            windowNavigated(win.id, path, title)
            // Back and forward can step a window that is behind others, so that window comes to the front.
            if (traversed) {
                focusWindow(win.id)
            }
        })
        // A click into a frame never reaches this page, so the frame reports it. Frame `focus` events are
        // not used, because an app that focuses an input on load would steal focus from the window on top.
        const focusThisWindow = (): void => focusWindow(win.id)
        let frameWindow: Window | null = null
        try {
            frameWindow = frame.contentWindow
            frameWindow?.addEventListener('pointerdown', focusThisWindow, true)
        } catch {
            frameWindow = null
        }
        stopWatchingFrame.current = () => {
            stopWatching()
            try {
                frameWindow?.removeEventListener('pointerdown', focusThisWindow, true)
            } catch {
                // The frame left this origin, and its listeners went away with its document.
            }
        }
    }

    const transition = { duration: reduceMotion ? 0 : 0.2, ease: [0.2, 0.2, 0.8, 1] as const }
    const zoomFrom = win.minimized
        ? { x: desktop.width / 2 - bounds.x, y: desktop.height - bounds.y }
        : zoomOrigin
          ? { x: zoomOrigin.x - bounds.x, y: zoomOrigin.y - bounds.y }
          : null

    return (
        <motion.section
            className={cn(
                'absolute flex flex-col bg-surface-primary overflow-hidden border border-primary',
                win.maximized ? 'rounded-none' : 'rounded-md',
                focused ? 'shadow-2xl' : 'shadow-lg',
                win.minimized && 'pointer-events-none'
            )}
            style={{
                left: bounds.x,
                top: bounds.y,
                width: bounds.width,
                height: bounds.height,
                zIndex: win.zIndex,
                transformOrigin: zoomFrom ? `${zoomFrom.x}px ${zoomFrom.y}px` : 'center',
            }}
            initial={{ opacity: 0, scale: zoomOrigin ? 0.08 : 0.96 }}
            animate={
                win.minimized
                    ? { opacity: 0, scale: 0.1, transitionEnd: { visibility: 'hidden' } }
                    : { opacity: 1, scale: 1, visibility: 'visible' }
            }
            exit={{ opacity: 0, scale: 0.96 }}
            transition={transition}
            aria-label={win.title}
            aria-hidden={win.minimized || undefined}
            data-attr="os-window"
            data-os-window-id={win.id}
            data-focused={focused || undefined}
            onPointerDownCapture={() => !focused && focusWindow(win.id)}
        >
            <header
                className={cn(
                    'flex items-center gap-2 h-8 shrink-0 pl-3 pr-1 border-b border-primary select-none cursor-move touch-none',
                    focused ? 'bg-surface-secondary' : 'bg-surface-primary'
                )}
                onPointerDown={(event) => {
                    if (!(event.target as HTMLElement).closest('button')) {
                        startGesture('move', event)
                    }
                }}
                onDoubleClick={(event) => {
                    if (!(event.target as HTMLElement).closest('button')) {
                        toggleMaximize()
                    }
                }}
                {...gestureHandlers}
            >
                <h2 className={cn('flex-1 m-0 text-sm font-semibold truncate', !focused && 'text-secondary')}>
                    {win.title}
                </h2>
                <div className="flex items-center gap-0.5 shrink-0">
                    <LemonButton
                        size="xsmall"
                        icon={<IconMinus />}
                        onClick={() => minimizeWindow(win.id)}
                        tooltip={<ShortcutHint label="Minimize" command="minimize" />}
                        aria-label="Minimize"
                        data-attr="os-window-minimize"
                    />
                    <LemonButton
                        size="xsmall"
                        icon={win.maximized ? <IconCollapse45Chevrons /> : <IconExpand45Chevrons />}
                        onClick={toggleMaximize}
                        tooltip={
                            <ShortcutHint
                                label={win.maximized ? 'Restore size' : 'Maximize'}
                                command="toggle-maximize"
                            />
                        }
                        aria-label={win.maximized ? 'Restore size' : 'Maximize'}
                        data-attr="os-window-maximize"
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={() => closeWindow(win.id)}
                        tooltip={<ShortcutHint label="Close" command="close" />}
                        aria-label="Close"
                        data-attr="os-window-close"
                    />
                </div>
            </header>
            {src && (
                <iframe
                    name={osFrameName(win.id)}
                    src={src}
                    title={win.title}
                    className={cn(
                        'flex-1 w-full min-h-0 border-0 bg-surface-primary',
                        interacting && 'pointer-events-none'
                    )}
                    onLoad={(event) => onFrameLoad(event.currentTarget)}
                />
            )}
            {!win.maximized &&
                RESIZE_HANDLES.map(({ edge, className }) => (
                    <div
                        key={edge}
                        aria-hidden
                        className={cn('absolute touch-none', className)}
                        onPointerDown={(event) => startGesture(edge, event)}
                        {...gestureHandlers}
                    />
                ))}
        </motion.section>
    )
}
