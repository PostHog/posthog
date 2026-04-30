import type { MutableRefObject } from 'react'
import { useEffect, useRef } from 'react'

// Latest value in a ref, written post-commit. For render-time reads use useLatestSync.
export function useLatest<T>(value: T): MutableRefObject<T> {
    const ref = useRef<T>(value)
    useEffect(() => {
        ref.current = value
    }, [value])
    return ref
}

// Like useLatest but writes during render — only when consumers read the ref during their own render.
export function useLatestSync<T>(value: T): MutableRefObject<T> {
    const ref = useRef<T>(value)
    ref.current = value
    return ref
}
