/**
 * Example bundle wiring check — `services/agent-tests/src/examples/agent-builder/`.
 *
 * The Agent Builder authors + operates other agents through the PostHog MCP
 * (one `spec.mcps[]` entry authed by the `posthog` identity provider), acting
 * as the asking user. It keeps only its own runtime natives (`@posthog/memory-*`
 * plus `@posthog/web-search`) and the PostHog Code client/UI tools. Destructive authoring ops
 * (`promote` / `archive` / `destroy`) are approval-gated on the MCP `tools[]`
 * via `level: 'approve'` + `approval_policy`, so the platform — not
 * just the prompt — holds them. This case pins that wiring net; drift here
 * means the bundle is broken regardless of platform readiness.
 *
 * Faux net — wiring, not inference quality.
 */

import { execFile } from 'node:child_process'
import { cp, mkdir, mkdtemp, readdir, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

import { AgentSpecSchema } from '@posthog/agent-shared'
import { listNativeTools } from '@posthog/agent-tools'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/agent-builder')
const execFileAsync = promisify(execFile)

async function loadBundle(): Promise<{ spec: Record<string, unknown>; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as Record<string, unknown>
    const files: Record<string, string> = {}
    files['agent.md'] = await readFile(join(BUNDLE_ROOT, 'agent.md'), 'utf-8')
    files['README.md'] = await readFile(join(BUNDLE_ROOT, 'README.md'), 'utf-8')
    return { spec, files }
}

describe('example: agent-builder bundle', () => {
    it('parses through AgentSpecSchema — the runner accepts it as-is', async () => {
        const { spec } = await loadBundle()
        expect(() => AgentSpecSchema.parse(spec)).not.toThrow()
    })

    it('carries NO inline skills — kernel skills are platform-injected, playbooks are MCP', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        // The author-facing bundle never carries skills. Kernel skills (the
        // concierge's own runtime behaviour — safety, console UI, fleet audit)
        // are injected from backend code at freeze (logic/kernel_skills.py), so
        // they move in lockstep with the platform and can't drift per account.
        // Builder playbooks (how to author/edit/wire-identity an agent) are served
        // by the MCP `agent-resolve-resource`, fetched on demand. Neither is here.
        expect(parsed.skills).toEqual([])
    })

    it('agent.md is present and non-trivial', async () => {
        const { files } = await loadBundle()
        expect(files['agent.md'].length).toBeGreaterThan(500)
    })

    it('authors via ONE PostHog MCP authed by the posthog identity provider', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        expect(parsed.mcps).toHaveLength(1)
        expect(parsed.mcps[0].id).toBe('posthog')
        expect(parsed.mcps[0].auth?.provider).toBe('posthog')
        // The curated allow-list keeps the surface to authoring + data tools.
        expect(parsed.mcps[0].tools?.length ?? 0).toBeGreaterThan(20)
    })

    it('keeps only its own runtime natives (memory + web-search) — no native agent-applications tools', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const nativeIds = parsed.tools.filter((t) => t.kind === 'native').map((t) => t.id)
        // The authoring surface moved to the MCP; the only natives left are the
        // agent's own runtime tools — S3 memory plus web search.
        expect(nativeIds.every((id) => id.startsWith('@posthog/memory-') || id === '@posthog/web-search')).toBe(true)
        expect(nativeIds.some((id) => id.startsWith('@posthog/agent-applications-'))).toBe(false)
        // Whatever natives remain must still resolve in the catalog.
        const catalog = new Set(listNativeTools().map((t) => t.id))
        for (const id of nativeIds) {
            expect(catalog.has(id), `${id} should be a known native tool`).toBe(true)
        }
    })

    it('declares chat + mcp triggers and NO slack trigger', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const types = parsed.triggers.map((t) => t.type)
        expect(types).toEqual(expect.arrayContaining(['chat', 'mcp']))
        // No Slack: the canonical Agent Builder has no dedicated Slack app, and
        // a slack trigger makes promote refuse until SLACK_SIGNING_SECRET +
        // SLACK_BOT_TOKEN are set — re-adding it breaks the seeded deployment.
        expect(types).not.toContain('slack')
    })

    it('declares a posthog identity provider with the scopes authoring needs', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const posthog = parsed.identity_providers.find((p) => p.kind === 'posthog')
        expect(posthog).not.toBeUndefined()
        const scopes = posthog?.scopes ?? []
        // user:read backs the MCP's /api/users/@me/ bootstrap; agents:write backs
        // authoring other agents. Both are load-bearing — pin them.
        expect(scopes).toEqual(expect.arrayContaining(['user:read', 'agents:read', 'agents:write']))
    })

    it('declares the client tools the console UI implements', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const ids = parsed.tools
            .filter((t): t is Extract<typeof t, { kind: 'client' }> => t.kind === 'client')
            .map((t) => t.id)
            .sort()
        expect(ids).toEqual([
            'connect_mcp',
            'focus_file',
            'focus_revision',
            'focus_session',
            'focus_spec_section',
            'focus_tab',
            'get_context',
            'set_secret',
            'toast',
        ])
    })

    it('requires the user PostHog bearer for chat instead of silently losing MCP credentials', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const modesFor = (type: string): string[] => {
            const t = parsed.triggers.find((x) => x.type === type)
            return t && 'auth' in t && t.auth ? (t.auth.modes?.map((m) => m.type) ?? []) : []
        }
        expect(modesFor('chat')).toEqual(['posthog'])
        expect(modesFor('mcp')).toEqual(['posthog', 'posthog_internal'])
    })

    it('enables resume so multi-step flows can span days', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        expect(parsed.resume?.enabled).toBe(true)
        expect(parsed.resume?.max_completed_age_ms).toBeGreaterThanOrEqual(7 * 24 * 60 * 60 * 1000)
    })

    it('gates destructive MCP authoring tools (promote / archive / destroy) with principal approval', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const entries = parsed.mcps[0].tools ?? []
        // `level: 'approve'` entries carry the approval policy — that's how the
        // platform (not just the prompt) holds a destructive authoring op.
        const gated = new Map(entries.filter((e) => e.level === 'approve').map((e) => [e.name, e]))
        for (const name of [
            'agent-applications-revisions-promote-create',
            'agent-applications-revisions-archive-create',
            'agent-applications-destroy',
        ]) {
            expect(gated.has(name), `${name} should be approval-gated`).toBe(true)
            expect(gated.get(name)?.approval_policy?.type).toBe('principal')
        }
    })

    it('every bundle/tests/*.json case parses and declares the required fields', async () => {
        const testsDir = join(BUNDLE_ROOT, 'tests')
        const jsonFiles = (await readdir(testsDir)).filter((f) => f.endsWith('.json'))
        expect(jsonFiles.length).toBeGreaterThanOrEqual(5)
        for (const f of jsonFiles) {
            const body = JSON.parse(await readFile(join(testsDir, f), 'utf-8')) as {
                name?: string
                description?: string
                trigger?: { type: string }
                expected?: Record<string, unknown>
            }
            expect(body.name, `${f}: name`).toBeTruthy()
            expect(body.description, `${f}: description`).toBeTruthy()
            expect(body.trigger?.type, `${f}: trigger.type`).toBeTruthy()
            expect(body.expected, `${f}: expected`).toBeTruthy()
        }
    })

    it('the shared example seeder deploys this bundle without stripping mcps', async () => {
        const scriptPath = resolve(__dirname, '../examples/seed.py')
        const src = await readFile(scriptPath, 'utf-8')
        expect(src.startsWith('#!/usr/bin/env python3')).toBe(true)
        expect(src).toContain('def per_file_sha256(')
        // The bundle now SHIPS an MCP — the seeder must never blank mcps[].
        expect(src).not.toContain('spec["mcps"] = []')
    })

    it('the shared example seeder starts from the production sparse checkout', async () => {
        const tempRoot = await mkdtemp(join(tmpdir(), 'agent-builder-seed-'))
        const sparseExamplesRoot = join(tempRoot, 'products/agent_platform/services/agent-tests/src/examples')

        try {
            await mkdir(dirname(sparseExamplesRoot), { recursive: true })
            await cp(resolve(__dirname, '../examples'), sparseExamplesRoot, { recursive: true })

            const { stdout } = await execFileAsync('python3', [join(sparseExamplesRoot, 'seed.py'), '--list'], {
                env: { ...process.env, SEED_DUMMY_SECRETS: '0' },
            })

            expect(stdout).toContain('agent-builder')
        } finally {
            await rm(tempRoot, { recursive: true, force: true })
        }
    })
})
