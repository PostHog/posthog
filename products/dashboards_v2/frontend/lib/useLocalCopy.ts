import { Dispatch, SetStateAction, useEffect, useRef, useState } from 'react'

// A copy of a panel for a form to edit freely. It saves the whole copy after `delay` of quiet, and again on unmount.
export function useLocalCopy<T extends object>(
    value: T,
    save: (next: T) => void,
    delay = 300
): [T, Dispatch<SetStateAction<T>>, () => void] {
    const [local, setLocal] = useState(value)
    const saved = useRef(value)
    const latest = useRef({ local, save })
    latest.current = { local, save }

    useEffect(() => {
        if (value !== saved.current) {
            saved.current = value
            setLocal(value)
        }
    }, [value])

    const flush = useRef(() => {
        const { local: current, save: persist } = latest.current
        if (current !== saved.current) {
            saved.current = current
            persist(current)
        }
    }).current

    useEffect(() => {
        if (local === saved.current) {
            return
        }
        const timer = setTimeout(flush, delay)
        return () => clearTimeout(timer)
    }, [local, delay, flush])

    useEffect(() => flush, [flush])

    return [local, setLocal, flush]
}
