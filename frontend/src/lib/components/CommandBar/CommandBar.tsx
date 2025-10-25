import './index.scss'

import { useActions, useValues } from 'kea'
import { forwardRef, useRef } from 'react'

import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'

import { ActionBar } from './ActionBar'
import { SearchBar } from './SearchBar'
import { Shortcuts } from './Shortcuts'
import { commandBarLogic } from './commandBarLogic'
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
        <div className="CommandBar__overlay fixed group/colorful-product-icons colorful-product-icons-true">
            <div className="CommandBar__overlay-content">
                <div
                    data-attr="command-bar"
                    className={`w-full ${
                        barStatus === BarStatus.SHOW_SEARCH && 'h-full'
                    } w-full bg-primary rounded overflow-hidden border border-primary`}
                    ref={ref}
                >
                    {children}
                </div>
            </div>
        </div>
    )
})

export function CommandBar(): JSX.Element | null {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { barStatus } = useValues(commandBarLogic)
    const { hideCommandBar } = useActions(commandBarLogic)

    useOutsideClickHandler(
        [containerRef],
        () => {
            if (barStatus !== BarStatus.HIDDEN) {
                hideCommandBar()
            }
        },
        [barStatus]
    )

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
