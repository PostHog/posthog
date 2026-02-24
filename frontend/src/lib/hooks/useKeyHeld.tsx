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

    useEventListener('keyup', (event) => {
        if (event.key === key && isHeldRef.current) {
            isHeldRef.current = false
            setKeyHeld(false)
        }
    })

    return keyHeld
}
