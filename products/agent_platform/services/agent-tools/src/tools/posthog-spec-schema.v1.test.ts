import { describe, expect, it } from 'vitest'

import type { ToolContext } from '@posthog/agent-shared'

import { getNativeTool } from '../registry'
import { posthogAgentApplicationsSpecSchemaV1 } from './posthog-spec-schema.v1'

describe('@posthog/agent-applications-spec-schema', () => {
    it('is registered and resolvable by id', () => {
        expect(getNativeTool('@posthog/agent-applications-spec-schema')).toBe(posthogAgentApplicationsSpecSchemaV1)
    })

    it('returns the spec JSON Schema generated from the canonical AgentSpecSchema', async () => {
        const result = await posthogAgentApplicationsSpecSchemaV1.run({}, {} as ToolContext)
        const schema = result.spec_json_schema as Record<string, unknown>
        // `model` is the only always-required field; everything else has a default.
        expect(schema.type).toBe('object')
        expect((schema.required as string[]) ?? []).toContain('model')
        expect(schema.properties).toHaveProperty('triggers')
        expect(schema.properties).toHaveProperty('tools')
        expect(schema.properties).toHaveProperty('secrets')
    })

    it('encodes the exact constructs that trip up authoring', async () => {
        const { spec_json_schema } = await posthogAgentApplicationsSpecSchemaV1.run({}, {} as ToolContext)
        // One serialized blob is the simplest way to assert the union/enum shapes
        // survive the JSON-Schema conversion (chat-trigger auth, reasoning enum,
        // the secrets string|object union with required allowed_hosts).
        const blob = JSON.stringify(spec_json_schema)
        expect(blob).toContain('acknowledge_public_exposure')
        expect(blob).toContain('allowed_hosts')
        expect(blob).toContain('xhigh')
        expect(blob).toContain('trusted_workspaces')
    })

    it('returns orientation notes', async () => {
        const { notes } = await posthogAgentApplicationsSpecSchemaV1.run({}, {} as ToolContext)
        expect(notes.length).toBeGreaterThan(0)
        expect(notes.every((n) => typeof n === 'string' && n.length > 0)).toBe(true)
    })
})
