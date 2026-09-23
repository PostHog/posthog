import './TerminalFramebufferWindow.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { IconExpand, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DraggableWithSnapZones } from 'lib/components/DraggableWithSnapZones/DraggableWithSnapZones'

import { terminalLogic } from './terminalLogic'

export function TerminalFramebufferWindow(): JSX.Element | null {
    const { displayOpen } = useValues(terminalLogic)
    const {
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
    const [fullscreen, setFullscreen] = useState(false)
    const [captured, setCaptured] = useState(false)
    const [error, setError] = useState<string | null>(null)

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
    }, [displayOpen, attachDisplay, detachDisplay, releaseDisplayInput])

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
                className="TerminalFramebufferWindow rounded border bg-surface-primary shadow-lg overflow-hidden flex flex-col"
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
                    />
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
                    aria-label="Game display. Arrow keys move, Ctrl fires, Space opens doors, Escape opens the game menu. Shift+Tab releases keyboard focus."
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
                    onLostPointerCapture={releaseDisplayInput}
                    onPointerCancel={releaseDisplayInput}
                    onPointerMove={(event) => {
                        if (
                            document.pointerLockElement === event.currentTarget ||
                            (document.activeElement === event.currentTarget && event.buttons)
                        ) {
                            displayMouse(event.movementX, event.movementY)
                        }
                    }}
                    onContextMenu={(event) => event.preventDefault()}
                />
                <div className="text-xs text-secondary px-3 py-2 border-t shrink-0">
                    <span>
                        Arrows move · Ctrl fires · Space opens doors · Shift runs · Esc opens the menu or releases the
                        mouse · Shift+Tab releases keyboard focus
                    </span>
                    {error && (
                        <p className="text-danger mb-0 mt-1" role="status">
                            {error}
                        </p>
                    )}
                </div>
            </div>
        </DraggableWithSnapZones>,
        document.body
    )
}
