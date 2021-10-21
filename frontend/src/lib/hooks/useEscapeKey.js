import { useCallback, useEffect } from 'react'

export function useEscapeKey(callback, deps = []) {
    const escFunction = useCallback(
        (event) => {
            if (event.keyCode === 27) {
                callback()
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        deps
    )

    useEffect(
        () => {
            document.addEventListener('keydown', escFunction, false)
            return () => document.removeEventListener('keydown', escFunction, false)
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        deps
    )
}
