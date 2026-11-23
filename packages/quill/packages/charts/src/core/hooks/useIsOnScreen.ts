import { type RefObject, useEffect, useState } from 'react'

/** Whether the element is in the viewport. Observes only while `enabled`, so a page that is not
 *  zoomed runs no observer. Without IntersectionObserver every element counts as on screen. */
export function useIsOnScreen(ref: RefObject<Element>, enabled: boolean): boolean {
    const [onScreen, setOnScreen] = useState(typeof IntersectionObserver !== 'function')
    useEffect(() => {
        const element = ref.current
        if (!enabled || !element || typeof IntersectionObserver !== 'function') {
            return
        }
        const observer = new IntersectionObserver((entries) =>
            setOnScreen(entries[entries.length - 1]?.isIntersecting ?? false)
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [ref, enabled])
    return onScreen
}
