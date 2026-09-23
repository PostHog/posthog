import { useActions, useMountedLogic, useValues } from 'kea'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useLayoutEffect, useState } from 'react'

import { osBridgeLogic } from '../bridge/osBridgeLogic'
import { osAppPreviewLogic } from '../store/osAppPreviewLogic'
import { OsWindow } from './OsWindow'
import { OsSnapZone, snapZoneBounds } from './osWindowGeometry'
import { osWindowCommandFor } from './osWindowShortcuts'
import { osWindowsLogic } from './osWindowsLogic'

/** Fills its parent, so the shell decides where the desktop starts, for example below a menu bar. */
export function OsWindowLayer(): JSX.Element {
    useMountedLogic(osBridgeLogic)
    useMountedLogic(osAppPreviewLogic)
    const { windows, focusedWindow, desktop } = useValues(osWindowsLogic)
    const { setDesktopSize, runWindowCommand } = useActions(osWindowsLogic)
    const reduceMotion = useReducedMotion()
    const [desktopElement, setDesktopElement] = useState<HTMLDivElement | null>(null)
    const [interacting, setInteracting] = useState(false)
    const [snapPreview, setSnapPreview] = useState<OsSnapZone | null>(null)

    useLayoutEffect(() => {
        if (!desktopElement) {
            return
        }
        const report = (): void => {
            const { width, height } = desktopElement.getBoundingClientRect()
            setDesktopSize({ width: Math.round(width), height: Math.round(height) })
        }
        report()
        const observer = new ResizeObserver(report)
        observer.observe(desktopElement)
        return () => observer.disconnect()
    }, [desktopElement, setDesktopSize])

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            const command = osWindowCommandFor(event)
            if (command && !event.defaultPrevented) {
                event.preventDefault()
                runWindowCommand(command)
            }
        }
        document.addEventListener('keydown', onKeyDown)
        return () => document.removeEventListener('keydown', onKeyDown)
    }, [runWindowCommand])

    const preview = snapPreview ? snapZoneBounds(snapPreview, desktop) : null

    return (
        <div
            ref={setDesktopElement}
            className="relative isolate flex-1 min-h-0 w-full overflow-hidden"
            data-attr="os-window-layer"
        >
            <AnimatePresence>
                {preview && (
                    <motion.div
                        key="snap-preview"
                        className="absolute rounded-md border-2 border-accent bg-accent-highlight-secondary pointer-events-none"
                        style={{
                            left: preview.x,
                            top: preview.y,
                            width: preview.width,
                            height: preview.height,
                            zIndex: windows.length,
                        }}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 0.6 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: reduceMotion ? 0 : 0.15 }}
                        data-attr="os-window-snap-preview"
                    />
                )}
            </AnimatePresence>
            <AnimatePresence>
                {windows.map((w) => (
                    <OsWindow
                        key={w.id}
                        window={w}
                        focused={w.id === focusedWindow?.id}
                        desktopElement={desktopElement}
                        interacting={interacting}
                        onInteractionChange={setInteracting}
                        onSnapPreview={setSnapPreview}
                    />
                ))}
            </AnimatePresence>
        </div>
    )
}
