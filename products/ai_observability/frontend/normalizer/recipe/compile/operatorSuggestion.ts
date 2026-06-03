export function nearestOperator(key: string, operators: Iterable<string>): string | undefined {
    for (const op of operators) {
        if (withinOneEdit(key, op)) {
            return op
        }
    }
    return undefined
}

function withinOneEdit(a: string, b: string): boolean {
    if (a === b) {
        return false
    }
    if (Math.abs(a.length - b.length) > 1) {
        return false
    }
    let i = 0
    while (i < a.length && i < b.length && a[i] === b[i]) {
        i++
    }
    if (a.length === b.length) {
        return a.slice(i + 1) === b.slice(i + 1) // substitution
    }
    if (a.length < b.length) {
        return a.slice(i) === b.slice(i + 1) // insertion in b
    }
    return a.slice(i + 1) === b.slice(i) // deletion in b
}
