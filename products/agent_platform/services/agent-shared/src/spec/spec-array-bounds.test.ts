import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { AgentSpecSchema } from './spec'

/**
 * Tenant-array bounds totality (Coherence).
 *
 * Every top-level array in the agent spec is author-controlled and flows into a
 * loop/query at freeze/promote/run — an unbounded one is a resource lever (the
 * confirmed case: `identity_providers` fanning out into per-entry OAuthApplication
 * creation + org-row locks at promote). The convention "cap tenant arrays" was
 * applied to `mcps` alone and forgotten on five siblings. This oracle reads the
 * schema's OWN JSON-Schema projection (public API, not brittle zod internals) and
 * fails if any top-level array lacks `maxItems` — closing the class, so a new
 * array can't ship unbounded.
 */
describe('agent spec tenant-array bounds', () => {
    it('every top-level array field is bounded (maxItems)', () => {
        const js = z.toJSONSchema(AgentSpecSchema, { io: 'input' }) as {
            properties?: Record<string, { type?: string; items?: unknown; maxItems?: number; default?: unknown }>
        }
        const props = js.properties ?? {}
        const unbounded = Object.entries(props)
            .filter(([, p]) => p.type === 'array' || 'items' in p)
            .filter(([, p]) => typeof p.maxItems !== 'number')
            .map(([name]) => name)
        expect(unbounded, `unbounded tenant arrays — add .max(): ${unbounded.join(', ')}`).toEqual([])
    })
})
