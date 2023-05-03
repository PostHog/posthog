import { LemonDivider } from '@posthog/lemon-ui'
import { PlayerInspectorList } from './PlayerInspectorList'
import { PlayerInspectorControls } from './PlayerInspectorControls'
import { useEffect, useRef, useState } from 'react'
import { PlayerInspectorPreview } from './PlayerInspectorPreview'

const MOUSE_LEAVE_DELAY = 500

export function PlayerInspector({ onFocusChange }: { onFocusChange: (focus: boolean) => void }): JSX.Element {
    const [inspectorFocus, setInspectorFocus] = useState(false)
    const timeoutRef = useRef<any>(null)

    const clear = (): void => {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
    }

    const onInspectorEnter = (): void => {
        clear()
        setInspectorFocus(true)
    }

    const onInspectorLeave = (): void => {
        clear()
        timeoutRef.current = setTimeout(() => {
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
            <PlayerInspectorPreview />
        </div>
    )
}
