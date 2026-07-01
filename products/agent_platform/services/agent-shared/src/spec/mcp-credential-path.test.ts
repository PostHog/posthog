import { describe, expect, it } from 'vitest'

import { McpRefSchema } from './spec'

/**
 * Every `McpRef` must resolve its bearer through exactly ONE of three wired paths:
 *   - `connection`     (kind 'agent')     — shared mcp_store installation bearer
 *   - `auth.provider`  (kind 'principal') — per-asker linked identity
 *   - `secrets`/none   (kind 'agent')     — bring-your-own token, or a public MCP
 *
 * The `kind` discriminator + `superRefine` pin which fields a ref may set, so a
 * fourth path can't be smuggled in via a contradictory combination. This pins the
 * accept/reject matrix; loosening the refine fails it.
 */
const base = { id: 'm', url: 'https://mcp.example.test', default_tool_approval: 'approve' as const }

const cases: { name: string; ref: Record<string, unknown>; valid: boolean }[] = [
    { name: "principal + auth.provider (no connection)", ref: { ...base, kind: 'principal', auth: { provider: 'gh' } }, valid: true },
    { name: "principal WITHOUT auth.provider", ref: { ...base, kind: 'principal' }, valid: false },
    { name: "principal + connection (cross-path)", ref: { ...base, kind: 'principal', auth: { provider: 'gh' }, connection: 'inst-1' }, valid: false },
    { name: "agent + connection", ref: { ...base, kind: 'agent', connection: 'inst-1' }, valid: true },
    { name: "agent + secrets/headers (bring-your-own)", ref: { ...base, kind: 'agent', secrets: ['TOK'], headers: { Authorization: 'Bearer ${TOK}' } }, valid: true },
    { name: "agent + auth.provider (cross-path)", ref: { ...base, kind: 'agent', auth: { provider: 'gh' } }, valid: false },
    { name: "agent + nothing (public MCP, no auth)", ref: { ...base, kind: 'agent' }, valid: true },
]

describe('MCP credential-path totality', () => {
    it.each(cases)('$name → valid=$valid', ({ ref, valid }) => {
        expect(McpRefSchema.safeParse(ref).success).toBe(valid)
    })

    it('the discriminator is closed to exactly {agent, principal} — no third kind', () => {
        expect(McpRefSchema.safeParse({ ...base, kind: 'integration', connection: 'inst-1' }).success).toBe(false)
    })
})
