import type { z } from 'zod'

const results = new WeakMap<z.ZodType, WeakMap<object, z.ZodSafeParseResult<unknown>>>()

/**
 * Checks saved data against a schema. Saved objects never change, because every edit makes a new one, so the result is
 * kept per schema and object. A dashboard of many tiles then checks each config once, not on every render.
 */
export function parseOnce<T>(schema: z.ZodType<T>, value: unknown): z.ZodSafeParseResult<T> {
    if (typeof value !== 'object' || value === null) {
        return schema.safeParse(value)
    }
    let bySchema = results.get(schema)
    if (!bySchema) {
        bySchema = new WeakMap()
        results.set(schema, bySchema)
    }
    const known = bySchema.get(value) as z.ZodSafeParseResult<T> | undefined
    if (known) {
        return known
    }
    const result = schema.safeParse(value)
    bySchema.set(value, result)
    return result
}
