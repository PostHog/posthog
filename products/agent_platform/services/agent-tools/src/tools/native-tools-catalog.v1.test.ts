import { describe, expect, it } from 'vitest'

import { COST_HINTS, type ToolContext } from '@posthog/agent-shared'

import { listNativeTools, nativeToolsCatalogV1 } from '../registry'

describe('@posthog/agent-applications-native-tools-list', () => {
    it('returns the full native-tool catalog as id/description/requires/cost_hint', async () => {
        const result = await nativeToolsCatalogV1.run({}, {} as ToolContext)
        // Mirrors the registry exactly — same count, no run() leaked through.
        expect(result.tools).toHaveLength(listNativeTools().length)
        const byId = new Map(result.tools.map((t) => [t.id, t]))
        // A representative tool resolves with the expected shape.
        const query = byId.get('@posthog/query')
        expect(query).not.toBeUndefined()
        expect(typeof query!.description).toBe('string')
        expect(query!.requires.provider).toEqual({ id: 'posthog', scopes: ['query:read'] })
        expect(COST_HINTS).toContain(query!.cost_hint)
        // The catalog tool lists itself — it's a real available tool.
        expect(byId.has('@posthog/agent-applications-native-tools-list')).toBe(true)
    })
})
