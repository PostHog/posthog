const UUID_REGEX = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi

/**
 * Helper method that takes an object and replaces all UUIDs or given keys with placeholders
 */
export const forSnapshot = (
    obj: any,
    context?: { overrides?: Record<string, string>; idMap?: Record<string, string> }
) => {
    context = context ?? {}
    context.idMap = context.idMap ?? {}
    let res = obj
    if (Array.isArray(obj)) {
        res = obj.map((item) => forSnapshot(item, context))
    }

    if (obj && typeof obj === 'object') {
        for (const [key, value] of Object.entries(obj)) {
            if (context?.overrides?.[key]) {
                res[key] = context.overrides[key]
            } else {
                res[key] = forSnapshot(value, context)
            }
        }
    }

    if (typeof obj === 'string') {
        // Replace UUIDs with placeholders
        const matches = obj.match(UUID_REGEX)
        for (const match of matches ?? []) {
            context.idMap[match] = context.idMap[match] ?? `<REPLACED-UUID-${Object.keys(context.idMap).length}>`
            res = res.replace(match, context.idMap[match])
        }
    }

    return res
}
