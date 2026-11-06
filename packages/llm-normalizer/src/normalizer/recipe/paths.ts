export function readField(input: unknown, field: string): unknown {
    if (input && typeof input === 'object' && field in (input as object)) {
        return (input as Record<string, unknown>)[field]
    }
    return undefined
}

export function hasField(input: unknown, field: string): boolean {
    return !!input && typeof input === 'object' && field in input
}

export function readPath(input: unknown, segments: string[]): unknown {
    let cursor: unknown = input
    for (const seg of segments) {
        if (cursor && typeof cursor === 'object' && seg in (cursor as object)) {
            cursor = (cursor as Record<string, unknown>)[seg]
        } else {
            return undefined
        }
    }
    return cursor
}
