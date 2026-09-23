import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useLayoutEffect, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { terminalDockLogic } from './terminalDockLogic'
import { terminalLogic } from './terminalLogic'
import { TerminalView } from './TerminalView'

export function TerminalPanel(): JSX.Element | null {
    useMountedLogic(terminalLogic)
    const { dockOpen, hasOpened, terminalEnabled } = useValues(terminalDockLogic)
    const { setDockOpen } = useActions(terminalDockLogic)
    const { location } = useValues(router)
    const container = useRef<HTMLDivElement>(null)
    const resizeProps = {
        logicKey: 'terminal-dock',
        placement: 'top' as const,
        containerRef: container,
        persistent: true,
    }
    const { desiredSize } = useValues(resizerLogic(resizeProps))
    const { setDesiredSize } = useActions(resizerLogic(resizeProps))
    const fullScene = removeProjectIdIfPresent(location.pathname) === '/terminal'
    const visible = terminalEnabled && dockOpen && !fullScene
    useLayoutEffect(() => {
        const dock = container.current
        if (!visible || !dock) {
            return
        }
        const reserveSpace = (): void => {
            document.documentElement.style.setProperty(
                '--terminal-dock-height',
                `${dock.getBoundingClientRect().height}px`
            )
        }
        reserveSpace()
        const observer = new ResizeObserver(reserveSpace)
        observer.observe(dock)
        return () => {
            observer.disconnect()
            document.documentElement.style.removeProperty('--terminal-dock-height')
        }
    }, [visible])
    if (!hasOpened) {
        return null
    }
    return (
        <div
            ref={container}
            data-attr="terminal-dock"
            aria-label="Terminal panel"
            className={cn(
                'fixed inset-x-0 bottom-0 z-[calc(var(--z-scene-layout-content-panel)+1)] border-t bg-surface-primary shadow-lg pt-1 min-h-40 max-h-[80vh]',
                !visible && 'hidden'
            )}
            style={{ height: desiredSize ?? 320 }}
        >
            <Resizer {...resizeProps} />
            <button
                type="button"
                role="separator"
                aria-label="Resize terminal"
                aria-orientation="horizontal"
                aria-valuenow={desiredSize ?? 320}
                aria-valuemin={160}
                aria-valuemax={Math.floor(window.innerHeight * 0.8)}
                className="absolute top-0 left-1/2 w-12 h-1 rounded bg-border cursor-ns-resize focus-visible:ring"
                onKeyDown={(event) => {
                    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                        event.preventDefault()
                        setDesiredSize(
                            Math.max(
                                160,
                                Math.min(
                                    window.innerHeight * 0.8,
                                    (desiredSize ?? 320) + (event.key === 'ArrowUp' ? 40 : -40)
                                )
                            )
                        )
                    }
                }}
            />
            {visible && <TerminalView onClose={() => setDockOpen(false)} />}
        </div>
    )
}
