import { RefObject, useEffect, useRef } from 'react'

/**
 * Returns a ref that, when attached to a DOM element with running CSS or
 * Web Animations, cancels every animation on the element and its subtree
 * during React's unmount cleanup.
 *
 * Why this exists: Chromium's `DocumentTimeline` keeps a strong reference
 * to every running animation. A running animation keeps a strong reference
 * to its target element via `KeyframeEffect`. If a component unmounts
 * while an `animation: ... infinite` declaration is still running, the
 * detached subtree becomes pinned: timeline -> animation -> element ->
 * parent React tree. Across many SPA navigations this accumulates into
 * multi-GB tab memory.
 *
 * Cancelling animations on unmount severs the timeline back-reference so
 * the detached element (and its parent tree) can be garbage-collected
 * normally.
 */
export function useCancelAnimationsOnUnmount<T extends Element>(): RefObject<T> {
    const ref = useRef<T>(null)
    useEffect(() => {
        // Capture the element when the effect runs (ref is populated). If we
        // read ref.current inside the cleanup instead, React may have already
        // nulled the ref by then in some commit orderings, leaving the cancel
        // a no-op.
        const element = ref.current
        return () => {
            element?.getAnimations({ subtree: true }).forEach((a) => a.cancel())
        }
    }, [])
    return ref
}
