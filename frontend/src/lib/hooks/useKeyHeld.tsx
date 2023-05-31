import { useEventListener } from 'lib/hooks/useEventListener'
import { DependencyList, useEffect, useRef, useState } from 'react'

export function useKeyHeld(key: string, deps?: DependencyList): boolean {
    const keysHeldRef = useRef(new Set<string>())
    const [keyHeld, setKeyHeld] = useState(false)

    const checkKeysHeld = (): void => {
        setKeyHeld(keysHeldRef.current.has(key))
    }

    useEffect(() => {
        checkKeysHeld()
    }, [key, ...(deps || [])])

    useEventListener(
        'keydown',
        (event) => {
            const key = event.key
            const keysHeldCopy = new Set(keysHeldRef.current)
            keysHeldCopy.add(key)
            keysHeldRef.current = keysHeldCopy
            checkKeysHeld()
        },
        undefined,
        [...(deps || [])]
    )

    useEventListener(
        'keyup',
        (event) => {
            const key = event.key
            const keysHeldCopy = new Set(keysHeldRef.current)
            keysHeldCopy.delete(key)
            keysHeldRef.current = keysHeldCopy
            checkKeysHeld()
        },
        undefined,
        [...(deps || [])]
    )

    return keyHeld
}
