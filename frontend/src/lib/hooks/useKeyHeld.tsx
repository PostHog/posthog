import { useEventListener } from 'lib/hooks/useEventListener'
import { DependencyList, useState } from 'react'

export function useKeyHeld(deps?: DependencyList): Set<string> {
    const [keysHeld, setKeysHeld] = useState(new Set<string>())

    useEventListener(
        'keydown',
        (event) => {
            const key = event.key
            const keysHeldCopy = new Set(keysHeld)
            keysHeldCopy.add(key)
            setKeysHeld(keysHeldCopy)
        },
        undefined,
        [...(deps || [])]
    )

    useEventListener(
        'keyup',
        (event) => {
            const key = event.key
            const keysHeldCopy = new Set(keysHeld)
            keysHeldCopy.delete(key)
            setKeysHeld(keysHeldCopy)
        },
        undefined,
        [...(deps || [])]
    )

    return keysHeld
}
