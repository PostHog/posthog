import { useRef, useEffect } from 'react'

export function usePrevious(value) {
    const ref = useRef()
    useEffect(() => {
        ref.current = value
    })
    return ref.current
}
