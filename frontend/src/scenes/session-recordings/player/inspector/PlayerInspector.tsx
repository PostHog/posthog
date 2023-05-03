import { LemonDivider } from '@posthog/lemon-ui'
import { PlayerInspectorList } from './PlayerInspectorList'
import { PlayerInspectorControls } from './PlayerInspectorControls'
import { useEffect, useRef, useState } from 'react'

const MOUSE_LEAVE_DELAY = 500

export function PlayerInspector({ onFocusChange }: { onFocusChange: (focus: boolean) => void }): JSX.Element {
    const [inspectorFocus, setInspectorFocus] = useState(false)
    const timeoutRef = useRef<any>(null)

    const onInspectorEnter = (): void => {
        setInspectorFocus(true)
    }

    const onInspectorLeave = (): void => {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = setTimeout(() => {
            setInspectorFocus(false)
        }, MOUSE_LEAVE_DELAY)
    }

    // Behaves like a delayed hover where we will only close if the mouse is outside of the inspector for a certain time
    // but clicking outside will immediately close
    useEffect(() => {
        clearTimeout(timeoutRef.current)
        onFocusChange(inspectorFocus)

        if (!inspectorFocus) {
            return
        }

        const onClickHandler = (): void => {
            if (timeoutRef.current) {
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
            <LemonDivider className="my-0" />
            <PlayerInspectorList />
        </div>
    )
}
