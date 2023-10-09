import { useRef, forwardRef } from 'react'
import { useActions, useValues } from 'kea'

import { useEventListener } from 'lib/hooks/useEventListener'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'

import { commandBarLogic } from './commandBarLogic'
import { BarStatus } from './types'
import '../CommandPalette/index.scss'

const CommandBarOverlay = ({ children }: { children?: React.ReactNode }): JSX.Element => (
    <div
        className="fixed top-0 left-0 w-full h-full flex flex-col items-center"
        // eslint-disable-next-line react/forbid-dom-props
        style={{ zIndex: 'var(--z-command-palette)' }}
    >
        {children}
    </div>
)

const CommandBarContainer = forwardRef<HTMLDivElement, { children?: React.ReactNode }>(function CommandBarContainer(
    { children },
    ref
): JSX.Element {
    return (
        <div className="bg-white p-4" ref={ref}>
            {children}
        </div>
    )
})

function CommandBar(): JSX.Element | null {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { barStatus } = useValues(commandBarLogic)
    const { toggleSearchBar, toggleActionsBar, hideCommandBar } = useActions(commandBarLogic)

    useEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
            event.preventDefault()
            if (event.shiftKey) {
                toggleActionsBar()
            } else {
                toggleSearchBar()
            }
        }
    })

    useOutsideClickHandler(
        containerRef,
        () => {
            hideCommandBar()
        },
        []
    )

    if (barStatus === BarStatus.HIDDEN) {
        return null
    }

    return (
        <CommandBarOverlay>
            <CommandBarContainer ref={containerRef}>
                {barStatus === BarStatus.SHOW_ACTIONS && <div>Actions</div>}
                {barStatus === BarStatus.SHOW_SEARCH && <div>Search</div>}
            </CommandBarContainer>
        </CommandBarOverlay>
    )
}

export default CommandBar
