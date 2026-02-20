import { DependencyList, useEffect, useRef, useState } from 'react'

import { useEventListener } from 'lib/hooks/useEventListener'

export function useKeyHeld(key: string, deps?: DependencyList): boolean {
    const isHeldRef = useRef(false)
    const [keyHeld, setKeyHeld] = useState(false)

    useEffect(() => {
        setKeyHeld(isHeldRef.current)
    }, [key, ...(deps || [])]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEventListener(
        'keydown',
        (event) => {
            if (event.key === key && !isHeldRef.current) {
                isHeldRef.current = true
                setKeyHeld(true)
            }
        },
        undefined,
        [...(deps || [])]
    )

    useEventListener(
        'keyup',
        (event) => {
            if (event.key === key && isHeldRef.current) {
                isHeldRef.current = false
                setKeyHeld(false)
            }
        },
        undefined,
        [...(deps || [])]
    )

    return keyHeld
}
