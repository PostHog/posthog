/**
 * Example bundle wiring check — `services/agent-tests/src/examples/posthog-ai/`.
 *
 * PostHog AI answers questions via the PostHog MCP, acting as the asking user.
 * The contract this pins: a Slack trigger that ISN'T a shared thread (so the
 * asker's identity resolves), one MCP entry authed by the `posthog` identity
 * provider, and a declared posthog identity provider for the link flow. Drift
 * in any of those silently breaks "act as the user," so catch it here.
 *
 * Faux net — wiring, not inference quality.
 */

import { readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { AgentSpecSchema } from '@posthog/agent-shared'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/posthog-ai')

async function loadBundle(): Promise<{ spec: Record<string, unknown>; agentMd: string }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as Record<string, unknown>
    const agentMd = await readFile(join(BUNDLE_ROOT, 'agent.md'), 'utf-8')
    return { spec, agentMd }
}

describe('example: posthog-ai bundle', () => {
    it('parses through AgentSpecSchema — the runner accepts it as-is', async () => {
        const { spec } = await loadBundle()
        expect(() => AgentSpecSchema.parse(spec)).not.toThrow()
    })

    it('agent.md is present and non-trivial', async () => {
        const { agentMd } = await loadBundle()
        expect(agentMd.length).toBeGreaterThan(400)
    })

    it('is Slack-triggered and owner-only (so the asker identity resolves, not a shared thread)', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const slack = parsed.triggers.find((t) => t.type === 'slack')
        expect(slack).not.toBeUndefined()
        // Shared participant threads fail closed in the identity model — a Q&A
        // bot acting as the asker MUST be owner-only.
        expect(slack?.type === 'slack' && slack.config.allow_workspace_participants).toBe(false)
    })

    it('answers via one PostHog MCP authed by the posthog identity provider (no native tools)', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        expect(parsed.tools).toHaveLength(0)
        expect(parsed.mcps).toHaveLength(1)
        expect(parsed.mcps[0].auth?.provider).toBe('posthog')
    })

    it('declares a posthog identity provider with explicit read scopes for the link flow', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const posthog = parsed.identity_providers.find((p) => p.kind === 'posthog')
        expect(posthog).not.toBeUndefined()
        // Real scope objects, never the `*` wildcard — OAuth /authorize rejects
        // `*` (it's a PAT/first-party concept, not an OAuth-grantable scope).
        expect(posthog?.scopes).toContain('query:read')
        expect(posthog?.scopes).not.toContain('*')
        // principal binding (default) — per-asker, not a shared agent credential.
        expect(posthog?.binding).toBe('principal')
    })

    it('runs on an OpenAI model the local gateway supports', async () => {
        const { spec } = await loadBundle()
        expect(AgentSpecSchema.parse(spec).models).toEqual({
            mode: 'manual',
            models: [{ model: 'openai/gpt-5.5' }],
            optimize_for: 'cost',
        })
    })
})
