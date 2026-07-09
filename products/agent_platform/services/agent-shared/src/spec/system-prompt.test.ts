import {
    AgentSpecSchema,
    buildTestBundleStore,
    newTestPrefix,
    S3BundleStore,
    wipeTestPrefix,
} from '@posthog/agent-shared'

import { buildSystemPrompt } from './system-prompt'

let bundlePrefix: string
let bundleTestStore: ReturnType<typeof buildTestBundleStore>
let bundle: S3BundleStore

beforeEach(() => {
    bundlePrefix = newTestPrefix('agent_bundles_system_prompt_test')
    bundleTestStore = buildTestBundleStore(bundlePrefix)
    bundle = bundleTestStore.store
})

afterEach(async () => {
    await wipeTestPrefix(bundleTestStore.client, bundlePrefix).catch(() => undefined)
    bundleTestStore.client.destroy()
})

function makeRev(spec: ReturnType<typeof AgentSpecSchema.parse>): never {
    return {
        id: 'rev1',
        application_id: 'app',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-05-27',
        state: 'live',
        bundle_uri: 's3://x/',
        bundle_sha256: null,
        spec,
    } as never
}

describe('buildSystemPrompt', () => {
    it('reads agent.md and emits a skill INDEX (not bodies)', async () => {
        await bundle.write('rev1', 'agent.md', 'You are a helpful agent.')
        await bundle.write('rev1', 'skills/research/SKILL.md', 'Be thorough.')
        await bundle.write('rev1', 'skills/cite/SKILL.md', 'Cite sources.')
        const spec = AgentSpecSchema.parse({
            model: 'test/x',
            skills: [
                { id: 'research', path: 'skills/research/SKILL.md', description: 'How to research a question' },
                { id: 'cite', path: 'skills/cite/SKILL.md', description: 'Citation formatting' },
            ],
        })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)

        expect(prompt).toContain('You are a helpful agent.')
        // Index lists each skill with its id + description.
        expect(prompt).toContain('Available skills')
        expect(prompt).toContain('@posthog/load-skill')
        expect(prompt).toContain('`research`: How to research a question')
        expect(prompt).toContain('`cite`: Citation formatting')
        // Bodies must NOT be inlined — that's the whole point of B1.
        expect(prompt).not.toContain('Be thorough.')
        expect(prompt).not.toContain('Cite sources.')
    })

    it('skills without a description fall back to a placeholder in the index', async () => {
        await bundle.write('rev1', 'agent.md', 'top')
        const spec = AgentSpecSchema.parse({
            model: 'test/x',
            skills: [{ id: 'mystery', path: 'skills/mystery/SKILL.md' }],
        })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)
        expect(prompt).toContain('`mystery`: (no description)')
    })

    it('emits no skills section when spec.skills is empty', async () => {
        await bundle.write('rev1', 'agent.md', 'top')
        const spec = AgentSpecSchema.parse({ model: 'test/x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)
        expect(prompt).not.toContain('Available skills')
    })

    it('falls back when agent.md missing', async () => {
        const spec = AgentSpecSchema.parse({ model: 'x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)
        expect(prompt).toMatch(/missing agent\.md/)
    })

    it('injects the framework preamble before agent.md', async () => {
        await bundle.write('rev1', 'agent.md', 'I am the agent author content.')
        const spec = AgentSpecSchema.parse({ model: 'test/x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)

        // Preamble lands first so the author's instructions appear
        // *after* it — natural-language precedence lets agent.md
        // override the framework defaults.
        const preambleIdx = prompt.indexOf('Platform guidance')
        const authorIdx = prompt.indexOf('I am the agent author content.')
        expect(preambleIdx).toBeGreaterThanOrEqual(0)
        expect(authorIdx).toBeGreaterThan(preambleIdx)
    })

    it('framework preamble covers all default sections', async () => {
        await bundle.write('rev1', 'agent.md', 'x')
        const spec = AgentSpecSchema.parse({ model: 'test/x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)

        // §3.1 — meta-tool decision rules. Each of the two meta tools is
        // named and pi-ai will see explicit framing about when to use
        // which. Asking for input is just text + end-turn, not a tool.
        expect(prompt).toContain('@posthog/meta-end-turn')
        expect(prompt).toContain('@posthog/meta-end-session')
        expect(prompt).not.toContain('@posthog/meta-ask-for-input')
        // Default-first framing — the model should default to end-turn,
        // not end-session. The prose explicitly calls out end-turn as
        // the default; assert both terms colocate.
        const endTurnSection = prompt.split('@posthog/meta-end-turn')[1]?.split('@posthog/meta-end-session')[0] ?? ''
        expect(endTurnSection).toMatch(/default/i)

        // §3.2 — conversation-state contract.
        expect(prompt).toContain('Conversation state')
        expect(prompt).toMatch(/`completed`/)
        expect(prompt).toMatch(/`closed`/)

        // §3.3 — tool failure handling.
        expect(prompt).toMatch(/When a tool you called returns an error/i)

        // §3.4 — approval-gated tools.
        expect(prompt).toMatch(/approval-gated/i)
        expect(prompt).toContain('"state": "queued"')
    })

    it('spec.framework_prompt.omit suppresses specific sections', async () => {
        await bundle.write('rev1', 'agent.md', 'x')
        const spec = AgentSpecSchema.parse({
            model: 'test/x',
            framework_prompt: { omit: ['tool_failure_guidance', 'approval_guidance'] },
        })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)

        // Omitted sections dropped.
        expect(prompt).not.toMatch(/When a tool you called returns an error/i)
        expect(prompt).not.toMatch(/approval-gated/i)
        // Other sections still present.
        expect(prompt).toContain('@posthog/meta-end-turn')
        expect(prompt).toContain('Conversation state')
    })

    it('omits the unavailable-MCPs section when no failures are passed', async () => {
        await bundle.write('rev1', 'agent.md', 'x')
        const spec = AgentSpecSchema.parse({ model: 'test/x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)
        expect(prompt).not.toContain('Unavailable capabilities')
    })

    it('lists unavailable MCPs with the category hint, no raw error strings', async () => {
        await bundle.write('rev1', 'agent.md', 'x')
        const spec = AgentSpecSchema.parse({ model: 'test/x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle, {
            unavailableMcps: [
                { id: 'posthog', category: 'auth' },
                { id: 'linear', category: 'network' },
                { id: 'gh', category: 'not_found' },
                { id: 'mystery', category: 'unknown' },
            ],
        })
        expect(prompt).toContain('Unavailable capabilities')
        expect(prompt).toContain('`posthog` — authentication issue')
        expect(prompt).toContain('`linear` — network or upstream issue')
        expect(prompt).toContain('`gh` — endpoint not found')
        expect(prompt).toContain('`mystery` — unavailable')
        // The model is told not to paste raw error strings to the user.
        expect(prompt).toMatch(/do NOT paste raw error messages/)
    })

    it('renders a dead shared connection under "Disconnected integrations" — admin reconnect, not a retry', async () => {
        await bundle.write('rev1', 'agent.md', 'x')
        const spec = AgentSpecSchema.parse({ model: 'test/x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle, {
            unavailableMcps: [{ id: 'incident', category: 'connection_dead' }],
        })
        expect(prompt).toContain('Disconnected integrations')
        expect(prompt).toContain('`incident`')
        // Persistent + admin-owned: the asker can't fix a shared credential, so
        // the model must NOT imply a retry or a self-service reconnect.
        expect(prompt).toMatch(/administrator|admin|owner/i)
        expect(prompt).toMatch(/reconnect/i)
        expect(prompt).not.toMatch(/temporarily unavailable/i)
        // A dead connection is neither the asker's to connect nor a transient outage.
        expect(prompt).not.toContain('Connect required')
        expect(prompt).not.toContain('Unavailable capabilities')
        // Still never leak raw transport detail.
        expect(prompt).not.toMatch(/Bearer|http/)
    })

    it('renders a link-required MCP under "Connect required" with the URL, not as "unavailable"', async () => {
        await bundle.write('rev1', 'agent.md', 'x')
        const spec = AgentSpecSchema.parse({ model: 'test/x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle, {
            unavailableMcps: [
                { id: 'posthog', category: 'auth', authorizeUrl: 'https://app.posthog.test/oauth/authorize/?x=1' },
            ],
        })
        expect(prompt).toContain('Connect required')
        // Rendered as a markdown link (not a bare URL) so the model relays a clickable link.
        expect(prompt).toContain('`posthog`: [Connect posthog](https://app.posthog.test/oauth/authorize/?x=1)')
        expect(prompt).toMatch(/markdown link/)
        // A linkable failure must NOT land in the dead-end "Unavailable" block.
        expect(prompt).not.toContain('Unavailable capabilities')
    })

    it('reasoning hint only fires for high / xhigh', async () => {
        await bundle.write('rev1', 'agent.md', 'x')

        // No spec.reasoning → no hint.
        const noneSpec = AgentSpecSchema.parse({ model: 'test/x' })
        const nonePrompt = await buildSystemPrompt(makeRev(noneSpec), bundle)
        expect(nonePrompt).not.toMatch(/Reasoning budget/)

        // spec.reasoning: 'low' → no hint (normal model behaviour).
        const lowSpec = AgentSpecSchema.parse({ model: 'test/x', reasoning: 'low' })
        const lowPrompt = await buildSystemPrompt(makeRev(lowSpec), bundle)
        expect(lowPrompt).not.toMatch(/Reasoning budget/)

        // spec.reasoning: 'high' → hint injected.
        const highSpec = AgentSpecSchema.parse({ model: 'test/x', reasoning: 'high' })
        const highPrompt = await buildSystemPrompt(makeRev(highSpec), bundle)
        expect(highPrompt).toMatch(/Reasoning budget/)
        expect(highPrompt).toMatch(/extended reasoning/i)

        // Omit still wins over the hint.
        const omittedSpec = AgentSpecSchema.parse({
            model: 'test/x',
            reasoning: 'high',
            framework_prompt: { omit: ['reasoning_hint'] },
        })
        const omittedPrompt = await buildSystemPrompt(makeRev(omittedSpec), bundle)
        expect(omittedPrompt).not.toMatch(/Reasoning budget/)
    })

    it('adds the Slack reply-relay note only when slackReplyRelay is set', async () => {
        await bundle.write('rev1', 'agent.md', 'You are a helpful agent.')
        const spec = AgentSpecSchema.parse({ model: 'test/x' })

        const off = await buildSystemPrompt(makeRev(spec), bundle)
        expect(off).not.toMatch(/Responding in Slack/)

        const on = await buildSystemPrompt(makeRev(spec), bundle, { slackReplyRelay: true })
        expect(on).toMatch(/Responding in Slack/)
        expect(on).toMatch(/delivered to the thread automatically/i)
        expect(on).toContain('@posthog/slack-post-message')
    })
})
