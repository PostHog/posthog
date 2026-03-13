import { BuiltLogic, Logic, LogicWrapper, beforeUnmount, useMountedLogic } from 'kea'
import { useEffect, useRef, useState } from 'react'

/**
 * Attach a logic to another logic. The logics stay connected even if the React component unmounts.
 * The only way to detach them is to unmount the "attachTo" logic. If there are no other connections,
 * the "logic" will be unmounted as well.
 * */
export function useAttachedLogic(logic: BuiltLogic<Logic>, attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>): void {
    const [hasAttachTo] = useState(() => !!attachTo)
    const previousLogicPathRef = useRef<string | null>(null)

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
            const attachments = (attachTo as any).attachments as Record<string, () => void>

            const currentLogicPath = logic.pathString
            const previousLogicPath = previousLogicPathRef.current

            // If the logic changed (different pathString), clean up the old attachment
            if (previousLogicPath && previousLogicPath !== currentLogicPath) {
                attachments[previousLogicPath]?.()
            }

            // Create new attachment if it doesn't exist
            if (!attachments[currentLogicPath]) {
                const unmount = logic.mount()
                let mounted = true
                const detach = (): void => {
                    if (!mounted) {
                        return
                    }

                    mounted = false
                    if (attachments[currentLogicPath] === detach) {
                        delete attachments[currentLogicPath]
                    }
                    unmount()
                }

                attachments[currentLogicPath] = detach
                beforeUnmount(() => {
                    if (attachments[currentLogicPath] === detach) {
                        detach()
                    }
                })(builtAttachTo)
            }

            previousLogicPathRef.current = currentLogicPath
        }
    }, [attachTo, builtAttachTo, logic.pathString, logic]) // eslint-disable-line react-hooks/rules-of-hooks
}
