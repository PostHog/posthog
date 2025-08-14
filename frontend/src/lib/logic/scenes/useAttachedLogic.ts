import { useEffect } from 'react'
import { beforeUnmount, BuiltLogic, Logic, LogicWrapper, useMountedLogic } from 'kea'

/**
 * Attach a logic to another logic. The logics stay connected even if the React component unmounts.
 * The only way to detach them is to unmount the "attachTo" logic. If there are no other connections,
 * the "logic" will be unmounted as well.
 * */
export function useAttachedLogic(logic: BuiltLogic<Logic>, attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>): void {
    if (!attachTo) {
        // We're breaking the rules of hooks here...
        // You should not change the attachTo prop from undefined to defined
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
