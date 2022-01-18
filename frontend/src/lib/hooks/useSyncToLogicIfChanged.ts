import { useEffect } from 'react'
import { objectsEqual } from 'lib/utils'

/** if (oldValueInLogic != newValueInReact) setValueInLogic(newValue) */
export function useSyncToLogicIfChanged<T>(
    oldValueInLogic: T,
    newValueInReact: T,
    setValueInLogic: (newValue: T) => void
): void {
    useEffect(() => {
        if (!objectsEqual(oldValueInLogic, newValueInReact)) {
            setValueInLogic(newValueInReact)
        }
    }, [newValueInReact]) // only sync if new value changed
}
