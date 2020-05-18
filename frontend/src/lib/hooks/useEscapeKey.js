import { useCallback, useEffect } from 'react'

export function useEscapeKey(callback) {
    const escFunction = useCallback(event => {
        if (event.keyCode === 27) {
            callback()
        }
    }, [])

    useEffect(() => {
        document.addEventListener('keydown', escFunction, false)
        return () => document.removeEventListener('keydown', escFunction, false)
    }, [])
}
