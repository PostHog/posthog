import { useRef, forwardRef } from 'react'
import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'

import { commandBarLogic } from './commandBarLogic'
import { BarStatus } from './types'

import './index.scss'

const CommandBarOverlay = ({ children }: { children?: React.ReactNode }): JSX.Element => (
    <div
        className="fixed top-0 left-0 w-full h-full flex flex-col items-center justify-center"
        // eslint-disable-next-line react/forbid-dom-props
        style={{
            zIndex: 'var(--z-command-palette)',
            background: 'color-mix(in srgb, var(--bg-light) 75%, transparent)',
        }}
    >
        {children}
    </div>
)

const CommandBarContainer = forwardRef<HTMLDivElement, { children?: React.ReactNode }>(function CommandBarContainer(
    { children },
    ref
): JSX.Element {
    return (
        <div className="w-full h-160 max-w-lg bg-bg-light rounded overflow-hidden shadow-xl flex flex-col" ref={ref}>
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
                <div className="border-b">
                    <LemonInput
                        type="search"
                        className="command-bar__search-input"
                        fullWidth
                        suffix={<KeyboardShortcut escape muted />}
                        autoFocus
                    />
                </div>
            </CommandBarContainer>
        </CommandBarOverlay>
    )
}

export default CommandBar
