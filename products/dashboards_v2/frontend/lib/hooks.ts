import { useEffect, useState } from 'react'

export function useDebounced<T>(value: T, ms: number): T {
    const [settled, setSettled] = useState(value)
    useEffect(() => {
        const timer = setTimeout(() => setSettled(value), ms)
        return () => clearTimeout(timer)
    }, [value, ms])
    return settled
}

export function readStored<T>(key: string, fallback: T): T {
    try {
        const stored = localStorage.getItem(key)
        return stored === null ? fallback : (JSON.parse(stored) as T)
    } catch {
        return fallback
    }
}

export function pushRecent<T>(
    key: string,
    items: T[],
    max: number,
    same: (a: T, b: T) => boolean = (a, b) => a === b
): T[] {
    const kept = readStored<T[]>(key, []).filter((stored) => !items.some((item) => same(item, stored)))
    const list = [...items, ...kept].slice(0, max)
    localStorage.setItem(key, JSON.stringify(list))
    return list
}
