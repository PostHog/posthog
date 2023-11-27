import './index.scss'

import { useActions, useValues } from 'kea'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { forwardRef, useRef } from 'react'

import { ActionBar } from './ActionBar'
import { commandBarLogic } from './commandBarLogic'
import { SearchBar } from './SearchBar'
import { Shortcuts } from './Shortcuts'
import { BarStatus } from './types'

interface CommandBarOverlayProps {
    barStatus: BarStatus
    children?: React.ReactNode
}

const CommandBarOverlay = forwardRef<HTMLDivElement, CommandBarOverlayProps>(function CommandBarOverlayInternal(
    { barStatus, children },
    ref
): JSX.Element {
    return (
        <div
            className="fixed top-0 left-0 w-full h-full flex flex-col items-center justify-center p-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: 'var(--z-command-palette)',
                // background: 'color-mix(in srgb, var(--bg-light) 75%, transparent)',
                backgroundColor: 'var(--modal-backdrop-color)',
                backdropFilter: 'blur(var(--modal-backdrop-blur))',
            }}
        >
            <div
                data-attr="command-bar"
                className={`w-full ${
                    barStatus === BarStatus.SHOW_SEARCH && 'h-160'
                } max-w-lg bg-bg-3000 rounded overflow-hidden flex flex-col border shadow`}
                ref={ref}
            >
                {children}
            </div>
        </div>
    )
})

export function CommandBar(): JSX.Element | null {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { barStatus } = useValues(commandBarLogic)
    const { hideCommandBar } = useActions(commandBarLogic)

    useOutsideClickHandler(containerRef, hideCommandBar, [])

    if (barStatus === BarStatus.HIDDEN) {
        return null
    }

    return (
        <CommandBarOverlay barStatus={barStatus} ref={containerRef}>
            {barStatus === BarStatus.SHOW_SEARCH && <SearchBar />}
            {barStatus === BarStatus.SHOW_ACTIONS && <ActionBar />}
            {barStatus === BarStatus.SHOW_SHORTCUTS && <Shortcuts />}
        </CommandBarOverlay>
    )
}
