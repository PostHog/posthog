export function createSafeStorageEngine(reportFailure: (error: unknown) => void): Storage {
    const unsavedValues = new Map<string, string>()
    let failureReported = false

    function withLocalStorage<T>(operation: (backingStorage: Storage) => T, fallback: T): T {
        try {
            return operation(window.localStorage)
        } catch (error) {
            if (!failureReported) {
                failureReported = true
                reportFailure(error)
            }
            return fallback
        }
    }

    const storage: Storage = {
        get length(): number {
            return withLocalStorage((backingStorage) => backingStorage.length, unsavedValues.size)
        },
        key: (index) => withLocalStorage((backingStorage) => backingStorage.key(index), null),
        getItem: (key) =>
            unsavedValues.get(key) ?? withLocalStorage((backingStorage) => backingStorage.getItem(key), null),
        setItem: (key, value) => {
            const saved = withLocalStorage((backingStorage) => {
                backingStorage.setItem(key, value)
                return true
            }, false)
            if (saved) {
                unsavedValues.delete(key)
            } else {
                unsavedValues.set(key, value)
            }
        },
        removeItem: (key) => {
            unsavedValues.delete(key)
            withLocalStorage((backingStorage) => backingStorage.removeItem(key), undefined)
        },
        clear: () => {
            unsavedValues.clear()
            withLocalStorage((backingStorage) => backingStorage.clear(), undefined)
        },
    }

    return new Proxy(storage, {
        get: (target, property, receiver) =>
            typeof property === 'string' && !(property in target)
                ? (target.getItem(property) ?? undefined)
                : Reflect.get(target, property, receiver),
        set: (target, property, value, receiver) => {
            if (typeof property === 'string' && !(property in target)) {
                target.setItem(property, String(value))
                return true
            }
            return Reflect.set(target, property, value, receiver)
        },
    })
}
