import type { MutableRefObject } from 'react'
import { useEffect, useRef } from 'react'

/** Holds the latest value of a non-render-driving prop in a ref so callbacks can read
 *  it without being re-created on every change. The write happens in a `useEffect` so
 *  React's concurrent / strict-mode pre-commit renders don't observably mutate the ref.
 *
 *  Reads from the ref inside event handlers always see the value committed during the
 *  most recent render — the one the user is interacting with — because event handlers
 *  fire after the commit phase has run. Reads inside other effects or async work may
 *  observe a previous commit's value if they fire between render and commit; for those
 *  cases prefer threading the value through the effect's deps directly. */
export function useLatest<T>(value: T): MutableRefObject<T> {
    const ref = useRef<T>(value)
    useEffect(() => {
        ref.current = value
    }, [value])
    return ref
}
