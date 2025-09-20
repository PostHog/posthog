import { BuiltLogic, Logic, LogicWrapper, beforeUnmount, useMountedLogic } from 'kea'
import { useEffect, useState } from 'react'

/**
 * Attach a logic to another logic. The logics stay connected even if the React component unmounts.
 * The only way to detach them is to unmount the "attachTo" logic. If there are no other connections,
 * the "logic" will be unmounted as well.
 * */
export function useAttachedLogic(logic: BuiltLogic<Logic>, attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>): void {
    const [hasAttachTo] = useState(() => !!attachTo)
    if (hasAttachTo && !attachTo) {
        throw new Error("Can't reset the 'attachTo' prop after it was set during initialization.")
    } else if (!hasAttachTo && attachTo) {
        throw new Error("Can't redefine the 'attachTo' prop when it was initialized as undefined.")
    } else if (!attachTo) {
        // No attachTo prop, ignore all logic that follows.
        // We are breaking the rules of react here, but it's fine due to the extra checks above.
        return
    }
    const builtAttachTo = useMountedLogic(attachTo) // eslint-disable-line react-hooks/rules-of-hooks
    useEffect(() => {
        if (attachTo && builtAttachTo) {
            if (!('attachments' in attachTo)) {
                ;(attachTo as any).attachments = {} as Record<string, () => void>
            }
            if (!(attachTo as any).attachments[logic.pathString]) {
                const unmount = logic.mount()
                ;(attachTo as any).attachments[logic.pathString] = unmount
                beforeUnmount(() => {
                    unmount()
                })(builtAttachTo)
            }
        }
    }, [attachTo, builtAttachTo, logic.pathString, logic]) // eslint-disable-line react-hooks/rules-of-hooks
}
