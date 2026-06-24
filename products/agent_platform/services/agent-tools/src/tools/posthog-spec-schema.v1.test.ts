import { describe, expect, it } from 'vitest'

import type { ToolContext } from '@posthog/agent-shared'

import { getNativeTool } from '../registry'
import { posthogAgentApplicationsSpecSchemaV1 } from './posthog-spec-schema.v1'

const run = (args: { section?: string } = {}): ReturnType<typeof posthogAgentApplicationsSpecSchemaV1.run> =>
    posthogAgentApplicationsSpecSchemaV1.run(args as never, {} as ToolContext)

describe('@posthog/agent-applications-spec-schema', () => {
    it('is registered and resolvable by id', () => {
        expect(getNativeTool('@posthog/agent-applications-spec-schema')).toBe(posthogAgentApplicationsSpecSchemaV1)
    })

    it('returns the full spec JSON Schema when no section is given', async () => {
        const result = await run()
        expect(result.section).toBeNull()
        const schema = result.spec_json_schema as Record<string, unknown>
        expect(schema.type).toBe('object')
        expect((schema.required as string[]) ?? []).toContain('model')
        expect(schema.properties).toHaveProperty('triggers')
        expect(schema.properties).toHaveProperty('tools')
        expect(schema.properties).toHaveProperty('secrets')
    })

    it('dedupes repeated subschemas into $defs to keep the payload small', async () => {
        const { spec_json_schema } = await run()
        // `reused: 'ref'` hoists the auth-mode union / approval policy into
        // $defs instead of inlining a copy per trigger/tool — the whole point
        // of the token-spend fix. Assert the $ref machinery is actually used.
        expect(spec_json_schema.$defs).not.toBeUndefined()
        expect(JSON.stringify(spec_json_schema)).toContain('$ref')
    })

    it('encodes the exact constructs that trip up authoring', async () => {
        const blob = JSON.stringify((await run()).spec_json_schema)
        expect(blob).toContain('acknowledge_public_exposure')
        expect(blob).toContain('allowed_hosts')
        expect(blob).toContain('xhigh')
        expect(blob).toContain('trusted_workspaces')
    })

    it('returns only the requested slice for a section (much cheaper than the whole spec)', async () => {
        const full = JSON.stringify((await run()).spec_json_schema)
        const triggers = await run({ section: 'triggers' })
        expect(triggers.section).toBe('triggers')
        const triggersBlob = JSON.stringify(triggers.spec_json_schema)
        // The triggers slice carries trigger constructs but not, say, the spec's
        // limits field, and is meaningfully smaller than the full schema.
        expect(triggersBlob).toContain('trusted_workspaces')
        expect(triggersBlob.length).toBeLessThan(full.length)

        const limits = await run({ section: 'limits' })
        expect(limits.section).toBe('limits')
        const limitsBlob = JSON.stringify(limits.spec_json_schema)
        expect(limitsBlob).toContain('max_wall_seconds')
        expect(limitsBlob.length).toBeLessThan(triggersBlob.length)
    })

    it('scopes notes to the requested section', async () => {
        const triggers = await run({ section: 'triggers' })
        expect(triggers.notes.length).toBeGreaterThan(0)
        expect(triggers.notes.join(' ')).toMatch(/discriminated union on `type`/i)
        // A section fetch must not be padded with notes about other sections.
        expect(triggers.notes.join(' ')).not.toContain('allowed_hosts')
    })

    it('falls back to the full schema for an unknown section', async () => {
        const result = await run({ section: 'nonsense' })
        expect(result.section).toBeNull()
        expect(result.spec_json_schema.properties).toHaveProperty('triggers')
    })
})
