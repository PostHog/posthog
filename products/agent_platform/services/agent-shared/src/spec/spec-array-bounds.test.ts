import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { AgentSpecSchema } from './spec'

/**
 * Fails if any top-level spec array lacks `maxItems` (an unbounded author-controlled
 * array is a resource lever at freeze/promote/run). A naive `type === 'array'`
 * filter is a false-green trap — a nullable array projects to `anyOf` and a reused
 * schema to `$ref` — so we resolve `$ref` and walk `anyOf`/`oneOf`/`allOf`, plus a
 * floor on the detected count so the check can't pass vacuously.
 */

type JsonSchema = {
    type?: string
    items?: unknown
    maxItems?: number
    $ref?: string
    anyOf?: JsonSchema[]
    oneOf?: JsonSchema[]
    allOf?: JsonSchema[]
    properties?: Record<string, JsonSchema>
    $defs?: Record<string, JsonSchema>
}

/** Every array-typed subschema reachable from `node` (through $ref + combinators). */
function arraySchemasIn(
    node: JsonSchema | undefined,
    defs: Record<string, JsonSchema>,
    seen = new Set<string>()
): JsonSchema[] {
    if (!node) {
        return []
    }
    if (node.$ref) {
        const name = node.$ref.replace('#/$defs/', '')
        if (seen.has(name)) {
            return []
        }
        seen.add(name)
        return arraySchemasIn(defs[name], defs, seen)
    }
    const out: JsonSchema[] = []
    if (node.type === 'array') {
        out.push(node)
    }
    for (const branch of [...(node.anyOf ?? []), ...(node.oneOf ?? []), ...(node.allOf ?? [])]) {
        out.push(...arraySchemasIn(branch, defs, seen))
    }
    return out
}

const EXPECTED_MIN_ARRAY_FIELDS = 6 // triggers, tools, mcps, skills, identity_providers, secrets

describe('agent spec tenant-array bounds', () => {
    it('every top-level array field is bounded (maxItems), and we still detect them all', () => {
        const js = z.toJSONSchema(AgentSpecSchema, { io: 'input', unrepresentable: 'any' }) as JsonSchema
        const props = js.properties ?? {}
        const defs = js.$defs ?? {}

        const arrayFields: string[] = []
        const unbounded: string[] = []
        for (const [name, schema] of Object.entries(props)) {
            const arrays = arraySchemasIn(schema, defs)
            if (arrays.length === 0) {
                continue
            }
            arrayFields.push(name)
            if (arrays.some((a) => typeof a.maxItems !== 'number')) {
                unbounded.push(name)
            }
        }

        expect(unbounded, `unbounded tenant arrays — add .max(): ${unbounded.join(', ')}`).toEqual([])
        // Floor: if the projection ever stops surfacing the known arrays, fail loud
        // rather than pass vacuously (the false-green this oracle exists to prevent).
        expect(
            arrayFields.length,
            `only detected ${arrayFields.length} array fields (${arrayFields.join(', ')}); projection shape may have changed`
        ).toBeGreaterThanOrEqual(EXPECTED_MIN_ARRAY_FIELDS)
    })
})
