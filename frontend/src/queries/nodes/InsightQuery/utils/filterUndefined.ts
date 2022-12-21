export function filterUndefined<T extends Record<string | number | symbol, unknown>>(object: T): T {
    const newObject = { ...object }
    Object.keys(newObject).forEach((k) => {
        if (newObject[k] === undefined) {
            delete newObject[k]
        }
    })
    return newObject
}
