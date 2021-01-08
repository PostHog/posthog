export function getNextKey(arr) {
    if (arr.length === 0) {
        return -1
    }
    const result = arr.reduce((prev, curr) => (prev.id < curr.id ? prev : curr))
    if (result.id >= 0) {
        return -1
    } else {
        return result.id - 1
    }
}
