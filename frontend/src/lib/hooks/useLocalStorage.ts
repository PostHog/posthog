import { useCallback, useEffect, useState } from 'react'

function getStoredValue<T>(key: string, defaultValue: T): T {
    try {
        const item = localStorage.getItem(key)
        if (item === null) {
            return defaultValue
        }
        return JSON.parse(item) as T
    } catch {
        return defaultValue
    }
}

function setStoredValueInStorage<T>(key: string, value: T): void {
    try {
        localStorage.setItem(key, JSON.stringify(value))
    } catch {
        // Ignore localStorage errors (e.g., quota exceeded, disabled storage)
    }
}

export function useLocalStorage<T>(key: string, defaultValue: T): [T, (value: T | ((prev: T) => T)) => void] {
    const [storedValue, setStoredValue] = useState<T>(() => getStoredValue(key, defaultValue))

    useEffect(() => {
        const handleStorageChange = (e: StorageEvent): void => {
            if (e.key === key && e.newValue !== null) {
                try {
                    setStoredValue(JSON.parse(e.newValue) as T)
                } catch {
                    // Ignore parse errors
                }
            }
        }

        window.addEventListener('storage', handleStorageChange)
        return () => {
            window.removeEventListener('storage', handleStorageChange)
        }
    }, [key])

    const setValue = useCallback(
        (value: T | ((prev: T) => T)) => {
            const valueToStore = value instanceof Function ? value(storedValue) : value
            setStoredValue(valueToStore)
            setStoredValueInStorage(key, valueToStore)
        },
        [key, storedValue]
    )

    return [storedValue, setValue]
}
