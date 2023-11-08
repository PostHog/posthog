import { useRef, forwardRef } from 'react'
import { useActions, useValues } from 'kea'

import { useEventListener } from 'lib/hooks/useEventListener'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'

import { commandBarLogic } from './commandBarLogic'
import { BarStatus } from './types'

import './index.scss'
import SearchBar from './SearchBar'
import { LemonModal } from '@posthog/lemon-ui'

const CommandBarContainer = forwardRef<HTMLDivElement, { children?: React.ReactNode }>(function CommandBarContainer(
    { children },
    ref
): JSX.Element {
    return (
        <div className="w-full h-160 max-w-lg bg-bg-3000 rounded overflow-hidden flex flex-col" ref={ref}>
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
        } else if (event.key === 'Escape') {
            hideCommandBar()
        }
    })

    useOutsideClickHandler(containerRef, hideCommandBar, [])

    return (
        <LemonModal isOpen={barStatus !== BarStatus.HIDDEN} simple closable={false} width={800}>
            <CommandBarContainer ref={containerRef}>
                <SearchBar />
            </CommandBarContainer>
        </LemonModal>
    )
}

export default CommandBar
