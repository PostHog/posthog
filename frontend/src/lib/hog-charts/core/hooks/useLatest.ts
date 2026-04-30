import type { MutableRefObject } from 'react'
import { useRef } from 'react'

// Latest value of a prop in a ref, written during render so consumers see it from the same pass.
export function useLatest<T>(value: T): MutableRefObject<T> {
    const ref = useRef<T>(value)
    ref.current = value
    return ref
}
