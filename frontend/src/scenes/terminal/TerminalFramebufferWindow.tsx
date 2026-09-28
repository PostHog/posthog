import './TerminalFramebufferWindow.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { IconExpand, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DraggableWithSnapZones } from 'lib/components/DraggableWithSnapZones/DraggableWithSnapZones'

import { terminalLogic } from './terminalLogic'

export function TerminalFramebufferWindow(): JSX.Element | null {
    const {
        displayOpen,
        displayFullscreen: fullscreen,
        displayCaptured: captured,
        displayError: error,
    } = useValues(terminalLogic)
    const {
        setDisplayFullscreen: setFullscreen,
        setDisplayCaptured: setCaptured,
        setDisplayError: setError,
        closeDisplay,
        attachDisplay,
        detachDisplay,
        displayKey,
        displayButtons,
        displayMouse,
        releaseDisplayInput,
    } = useActions(terminalLogic)
    const windowRef = useRef<HTMLDivElement>(null)
    const screenRef = useRef<HTMLDivElement>(null)
    const resizeRef = useRef<{ x: number; y: number; width: number } | null>(null)

    const resizeWindow = (width: number): void => {
        const maximum = Math.min(window.innerWidth - 32, ((window.innerHeight - 160) * 4) / 3)
        windowRef.current?.style.setProperty('--terminal-display-width', `${Math.min(maximum, Math.max(480, width))}px`)
    }

    useEffect(() => {
        const screen = screenRef.current
        const frame = windowRef.current
        if (!displayOpen || !screen || !frame) {
            return
        }
        attachDisplay(screen)
        let focusFrame: number
        const focusWhenVisible = (): void => {
            if (getComputedStyle(screen).visibility === 'hidden') {
                focusFrame = requestAnimationFrame(focusWhenVisible)
            } else {
                screen.focus()
            }
        }
        focusFrame = requestAnimationFrame(focusWhenVisible)
        setError(null)
        const release = (): void => {
            releaseDisplayInput()
            if (document.pointerLockElement === screen) {
                document.exitPointerLock()
            }
        }
        const onVisibility = (): void => {
            if (document.hidden) {
                release()
            }
        }
        const onPointerLock = (): void => {
            setCaptured(document.pointerLockElement === screen)
            releaseDisplayInput()
        }
        const onFullscreen = (): void => setFullscreen(document.fullscreenElement === frame)
        const onPointerError = (): void => setError('Could not capture the mouse. Click Capture mouse to try again.')
        window.addEventListener('blur', release)
        document.addEventListener('visibilitychange', onVisibility)
        document.addEventListener('pointerlockchange', onPointerLock)
        document.addEventListener('pointerlockerror', onPointerError)
        document.addEventListener('fullscreenchange', onFullscreen)
        return () => {
            cancelAnimationFrame(focusFrame)
            release()
            detachDisplay()
            if (document.fullscreenElement === frame) {
                void document.exitFullscreen().catch(() => {})
            }
            window.removeEventListener('blur', release)
            document.removeEventListener('visibilitychange', onVisibility)
            document.removeEventListener('pointerlockchange', onPointerLock)
            document.removeEventListener('pointerlockerror', onPointerError)
            document.removeEventListener('fullscreenchange', onFullscreen)
        }
    }, [displayOpen, attachDisplay, detachDisplay, releaseDisplayInput, setCaptured, setFullscreen, setError])

    if (!displayOpen) {
        return null
    }

    return createPortal(
        <DraggableWithSnapZones
            handle=".TerminalFramebufferWindow__handle"
            defaultSnapPosition="top-right"
            onDragStart={releaseDisplayInput}
        >
            <div
                ref={windowRef}
                role="dialog"
                aria-label="Terminal display"
                aria-modal="false"
                className="TerminalFramebufferWindow relative rounded border bg-surface-primary shadow-lg overflow-hidden flex flex-col"
                data-attr="terminal-display-window"
            >
                <header className="flex items-center gap-1 border-b p-1 shrink-0">
                    <button
                        type="button"
                        className="TerminalFramebufferWindow__handle cursor-move select-none text-left font-semibold px-2 py-1 flex-1 min-w-0"
                        aria-label="Drag terminal display"
                        data-attr="terminal-display-drag"
                    >
                        Terminal display
                    </button>
                    <LemonButton
                        size="small"
                        onClick={() => {
                            const screen = screenRef.current
                            if (document.pointerLockElement === screen) {
                                document.exitPointerLock()
                            } else if (screen) {
                                setError(null)
                                screen.focus()
                                try {
                                    const result = screen.requestPointerLock()
                                    if (result) {
                                        void result.catch(() =>
                                            setError('Could not capture the mouse. Click Capture mouse to try again.')
                                        )
                                    }
                                } catch {
                                    setError('Mouse capture is unavailable. Use the keyboard controls.')
                                }
                            }
                        }}
                        data-attr="terminal-display-capture"
                    >
                        {captured ? 'Release mouse' : 'Capture mouse'}
                    </LemonButton>
                    <LemonButton
                        size="small"
                        icon={<IconExpand />}
                        aria-label={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
                        tooltip={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
                        onClick={() => {
                            const frame = windowRef.current
                            setError(null)
                            const request =
                                document.fullscreenElement === frame
                                    ? document.exitFullscreen()
                                    : frame?.requestFullscreen?.()
                            if (request) {
                                void request
                                    .then(() => screenRef.current?.focus())
                                    .catch(() =>
                                        setError('Fullscreen is unavailable. You can keep playing in this window.')
                                    )
                            } else {
                                setError('Fullscreen is unavailable. You can keep playing in this window.')
                            }
                        }}
                        data-attr="terminal-display-fullscreen"
                    >
                        {fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
                    </LemonButton>
                    <LemonButton
                        size="small"
                        icon={<IconX />}
                        aria-label="Close display and interrupt program"
                        tooltip="Close and interrupt (Ctrl+C)"
                        onClick={closeDisplay}
                        data-attr="terminal-display-close"
                    />
                </header>
                <div
                    ref={screenRef}
                    role="application"
                    aria-label="Game display. W and S move, A and D strafe, left and right arrows turn, Space fires, E opens doors. Shift+Tab releases keyboard focus."
                    tabIndex={0}
                    className="TerminalFramebufferWindow__screen ph-no-capture ph-replay-block flex-1 min-h-0 bg-black focus-visible:ring-2 focus-visible:ring-inset"
                    data-attr="terminal-display-screen"
                    data-shortcuts-ignore="all"
                    onKeyDown={(event) => {
                        if ((event.key === 'Tab' && event.shiftKey) || event.metaKey) {
                            releaseDisplayInput()
                            return
                        }
                        event.preventDefault()
                        event.stopPropagation()
                        displayKey(event.code, true)
                    }}
                    onKeyUp={(event) => {
                        if (!(event.key === 'Tab' && event.shiftKey) && !event.metaKey) {
                            event.preventDefault()
                            event.stopPropagation()
                            displayKey(event.code, false)
                        }
                    }}
                    onBlur={() => {
                        releaseDisplayInput()
                        if (document.pointerLockElement === screenRef.current) {
                            document.exitPointerLock()
                        }
                    }}
                    onPointerDown={(event) => {
                        event.currentTarget.focus()
                        if (document.pointerLockElement !== event.currentTarget) {
                            event.currentTarget.setPointerCapture(event.pointerId)
                        }
                        displayButtons(event.buttons)
                    }}
                    onPointerUp={(event) => displayButtons(event.buttons)}
                    onLostPointerCapture={() => displayButtons(0)}
                    onPointerCancel={releaseDisplayInput}
                    onPointerMove={(event) => {
                        displayButtons(event.buttons)
                        if (
                            document.pointerLockElement === event.currentTarget ||
                            (document.activeElement === event.currentTarget && event.buttons)
                        ) {
                            displayMouse(event.movementX, event.movementY)
                        }
                    }}
                    onContextMenu={(event) => event.preventDefault()}
                />
                <div className="text-xs text-secondary pl-3 pr-6 py-2 border-t shrink-0">
                    <span>
                        W/S move · A/D strafe · ←/→ turn · Space or click fires · E opens doors · Shift runs · Capture
                        mouse to turn · Esc opens the menu or releases the mouse · Shift+Tab releases keyboard focus
                    </span>
                    {error && (
                        <p className="text-danger mb-0 mt-1" role="status">
                            {error}
                        </p>
                    )}
                </div>
                {!fullscreen && (
                    <button
                        type="button"
                        aria-label="Resize terminal display"
                        title="Drag to resize. Arrow keys resize when focused."
                        className="TerminalFramebufferWindow__resize absolute bottom-0 right-0 w-5 h-5 cursor-nwse-resize touch-none"
                        data-attr="terminal-display-resize"
                        data-shortcuts-ignore="all"
                        onPointerDown={(event) => {
                            if (event.button !== 0 || !windowRef.current) {
                                return
                            }
                            releaseDisplayInput()
                            resizeRef.current = {
                                x: event.clientX,
                                y: event.clientY,
                                width: windowRef.current.getBoundingClientRect().width,
                            }
                            event.currentTarget.setPointerCapture(event.pointerId)
                        }}
                        onPointerMove={(event) => {
                            const start = resizeRef.current
                            if (start) {
                                const dx = event.clientX - start.x
                                const dy = ((event.clientY - start.y) * 4) / 3
                                resizeWindow(start.width + (Math.abs(dx) > Math.abs(dy) ? dx : dy))
                            }
                        }}
                        onPointerUp={(event) => {
                            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                                event.currentTarget.releasePointerCapture(event.pointerId)
                            }
                        }}
                        onLostPointerCapture={() => (resizeRef.current = null)}
                        onPointerCancel={() => (resizeRef.current = null)}
                        onKeyDown={(event) => {
                            if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
                                event.preventDefault()
                                event.stopPropagation()
                                const delta = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -32 : 32
                                resizeWindow((windowRef.current?.getBoundingClientRect().width ?? 672) + delta)
                            }
                        }}
                    />
                )}
            </div>
        </DraggableWithSnapZones>,
        document.body
    )
}
