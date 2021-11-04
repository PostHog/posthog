import React, { useRef, useMemo } from 'react'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { useMountedLogic, useValues, useActions } from 'kea'
import { commandPaletteLogic } from './commandPaletteLogic'
import { CommandInput } from './CommandInput'
import { CommandResults } from './CommandResults'
import { useEventListener } from 'lib/hooks/useEventListener'
import squeakFile from 'public/squeak.mp3'
import './index.scss'

export function CommandPalette(): JSX.Element | null {
    useMountedLogic(commandPaletteLogic)

    const { setInput, hidePalette, togglePalette, backFlow } = useActions(commandPaletteLogic)
    const { input, isPaletteShown, isSqueak, activeFlow, commandSearchResults } = useValues(commandPaletteLogic)

    const squeakAudio: HTMLAudioElement | null = useMemo(() => (isSqueak ? new Audio(squeakFile) : null), [isSqueak])

    const boxRef = useRef<HTMLDivElement | null>(null)

    useEventListener('keydown', (event) => {
        if (isSqueak && event.key === 'Enter') {
            squeakAudio?.play()
        } else if (event.key === 'Escape') {
            event.preventDefault()
            // Return to previous flow
            if (activeFlow) {
                backFlow()
            }
            // If no flw, erase input
            else if (input) {
                setInput('')
            }
            // Lastly hide palette
            else {
                hidePalette()
            }
        } else if (event.key === 'k' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault()
            togglePalette()
        }
    })

    useOutsideClickHandler(
        boxRef.current,
        () => {
            if (isPaletteShown) {
                hidePalette()
            }
        },
        [isPaletteShown]
    )

    return !isPaletteShown ? null : (
        <div className="palette__overlay">
            <div className="palette__box" ref={boxRef}>
                {(!activeFlow || activeFlow.instruction) && <CommandInput />}
                {!commandSearchResults.length && !activeFlow ? null : <CommandResults />}
            </div>
        </div>
    )
}
