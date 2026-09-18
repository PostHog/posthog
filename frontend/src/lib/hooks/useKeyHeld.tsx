import { useEffect, useRef, useState } from 'react'

import { useEventListener } from 'lib/hooks/useEventListener'

export function useKeyHeld(key: string): boolean {
    const isHeldRef = useRef(false)
    const [keyHeld, setKeyHeld] = useState(false)

    useEffect(() => {
        isHeldRef.current = false
        setKeyHeld(false)
    }, [key])

    useEventListener('keydown', (event) => {
        if (event.key === key && !isHeldRef.current) {
            isHeldRef.current = true
            setKeyHeld(true)
        }
    })

    const release = (): void => {
        if (isHeldRef.current) {
            isHeldRef.current = false
            setKeyHeld(false)
        }
    }

    useEventListener('keyup', (event) => {
        if (event.key === key) {
            release()
        }
    })

    // Alt+Tab and similar shortcuts move focus away before the keyup, so without this the key stays held forever
    useEventListener('blur', release)

    return keyHeld
}
