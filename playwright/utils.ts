export function randomString(prefix = ''): string {
    const id = Math.floor(Math.random() * 1e6)
    return `${prefix}-${id}`
}
