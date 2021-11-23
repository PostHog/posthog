import { useCallback, useEffect } from 'react'

export function useEscapeKey(callback, deps = []) {
    const escFunction = useCallback(
        (event) => {
            if (event.keyCode === 27) {
                callback()
            }
        },

        deps
    )

    useEffect(
        () => {
            document.addEventListener('keydown', escFunction, false)
            return () => document.removeEventListener('keydown', escFunction, false)
        },

        deps
    )
}
