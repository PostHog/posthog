import './index.scss'

import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { useRef } from 'react'

import ActionBar from './ActionBar'
import { commandBarLogic } from './commandBarLogic'
import SearchBar from './SearchBar'
import { BarStatus } from './types'

function CommandBar(): JSX.Element | null {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { barStatus } = useValues(commandBarLogic)
    const { hideCommandBar } = useActions(commandBarLogic)

    useOutsideClickHandler(containerRef, hideCommandBar, [])

    return (
        <LemonModal isOpen={barStatus !== BarStatus.HIDDEN} simple closable={false} width={800}>
            <div className="w-full h-160 max-w-lg bg-bg-3000 rounded overflow-hidden flex flex-col" ref={containerRef}>
                {barStatus === BarStatus.SHOW_SEARCH ? <SearchBar /> : <ActionBar />}
            </div>
        </LemonModal>
    )
}

export default CommandBar
