import { useEffect, useRef, useState } from 'react'

import { PlayerInspectorControls } from './PlayerInspectorControls'
import { PlayerInspectorList } from './PlayerInspectorList'
import { PlayerInspectorPreview } from './PlayerInspectorPreview'

const MOUSE_ENTER_DELAY = 100
const MOUSE_LEAVE_DELAY = 500

export function PlayerInspector({ onFocusChange }: { onFocusChange: (focus: boolean) => void }): JSX.Element {
    const [inspectorFocus, setInspectorFocus] = useState(false)
    const enterTimeoutRef = useRef<any>(null)
    const exitTimeoutRef = useRef<any>(null)

    const clear = (): void => {
        clearTimeout(exitTimeoutRef.current)
        clearTimeout(enterTimeoutRef.current)
        exitTimeoutRef.current = null
        enterTimeoutRef.current = null
    }

    const onInspectorEnter = (): void => {
        clear()
        enterTimeoutRef.current = setTimeout(() => {
            setInspectorFocus(true)
        }, MOUSE_ENTER_DELAY)
    }

    const onInspectorLeave = (): void => {
        clear()
        exitTimeoutRef.current = setTimeout(() => {
            setInspectorFocus(false)
        }, MOUSE_LEAVE_DELAY)
    }

    // Behaves like a delayed hover where we will only close if the mouse is outside of the inspector for a certain time
    // but clicking outside will immediately close
    useEffect(() => {
        clear()
        onFocusChange(inspectorFocus)

        if (!inspectorFocus) {
            return
        }

        const onClickHandler = (): void => {
            if (exitTimeoutRef.current) {
                setInspectorFocus(false)
            }
        }

        window.addEventListener('click', onClickHandler)

        return () => window.removeEventListener('click', onClickHandler)
    }, [inspectorFocus])

    return (
        <div
            className="SessionRecordingPlayer__inspector"
            onMouseEnter={onInspectorEnter}
            onMouseLeave={onInspectorLeave}
        >
            <PlayerInspectorControls />
            <PlayerInspectorList />
            <PlayerInspectorPreview />
        </div>
    )
}
