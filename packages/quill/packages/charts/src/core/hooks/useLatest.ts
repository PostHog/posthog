import type { MutableRefObject } from 'react'
import { useLayoutEffect, useRef } from 'react'

// written during render so consumers see it from the same render pass
export function useLatest<T>(value: T): MutableRefObject<T> {
    const ref = useRef<T>(value)
    ref.current = value
    return ref
}

/** Like {@link useLatest}, but written in a layout effect. Code that runs outside React's render, such
 *  as a store subscription, then never reads a value from a render that React threw away. */
export function useCommittedRef<T>(value: T): MutableRefObject<T> {
    const ref = useRef<T>(value)
    useLayoutEffect(() => {
        ref.current = value
    })
    return ref
}
