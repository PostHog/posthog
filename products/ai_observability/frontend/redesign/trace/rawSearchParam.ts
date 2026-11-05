// kea-router reads a numeric param as a number, which turns a typed `1.50` into `1.5`. It also pads a value shaped like
// a JSON array or object with one space, so it reads that value back as a string.
export function rawSearchParam(search: string, name: string): string | null {
    const value = new URLSearchParams(search).get(name)
    if (!value) {
        return null
    }
    return /^(\[.*\]|\{.*\}) +$/.test(value) ? value.slice(0, -1) : value
}
