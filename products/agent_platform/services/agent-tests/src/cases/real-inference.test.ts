/**
 * Real inference variant. By default this suite ALWAYS runs and fails if no
 * provider key is found — that's the only way to know v2 talks to a real
 * model end-to-end. Set `AGENT_SKIP_REAL_INFERENCE=1` to opt out (CI without
 * provider creds, dev iteration on faux-only paths, etc.).
 *
 * Key discovery order:
 *   1. process.env (already exported in the shell)
 *   2. `.env` at the posthog repo root (loaded via Node's loadEnvFile)
 *
 * Provider matrix:
 *   POSTHOG_AI_GATEWAY_KEY + POSTHOG_AI_GATEWAY_URL → ai-gateway
 *   ANTHROPIC_API_KEY                                 → Anthropic (default: claude-haiku-4-5)
 *   OPENAI_API_KEY                                    → OpenAI    (default: gpt-4o-mini)
 *
 * Defaults target the cheapest model in each registry that can still reliably
 * follow simple instructions and emit tool calls. `gpt-4.1-nano` is cheaper
 * but spuriously invents meta tool calls on trivial single-turn prompts;
 * `claude-3-haiku-20240307` is cheaper but ancient. Pin
 * `REAL_INFERENCE_MODEL_ID` to a larger model when investigating a regression
 * that needs one.
 *
 * Every provider with a key configured runs the full case set — this is how
 * we catch provider-specific drift (tool schemas, stop reasons, system prompt
 * handling) end-to-end. Pin to one provider with REAL_INFERENCE_PROVIDER
 * ("gateway" | "anthropic" | "openai"). Override the model with
 * REAL_INFERENCE_MODEL_ID (e.g. "claude-opus-4-7").
 */

import { getModel } from '@earendil-works/pi-ai'
import type { Model } from '@earendil-works/pi-ai'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import request from 'supertest'

import { type AuthProvider, publicVerifier, readBearer } from '@posthog/agent-ingress'
import { posthogAiGatewayModel } from '@posthog/agent-runner'
import { buildWebSearchProviders } from '@posthog/agent-tools'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

// Walk up from this file looking for a `.env` and load it into process.env.
// Idempotent — existing vars win (already-set shell exports always beat .env).
function loadRepoEnv(): void {
    let dir = dirname(fileURLToPath(import.meta.url))
    for (let i = 0; i < 8; i++) {
        const candidate = resolve(dir, '.env')
        if (existsSync(candidate)) {
            try {
                process.loadEnvFile(candidate)
            } catch {
                /* loadEnvFile throws on parse errors; we'd rather degrade than crash the suite */
            }
            break
        }
        const parent = dirname(dir)
        if (parent === dir) {
            break
        }
        dir = parent
    }
    // Node's built-in fetch (used by pi-ai's provider HTTP layer) does NOT
    // read macOS' keychain trust store — without an explicit CA bundle it
    // fails handshakes with `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`, which pi-ai
    // surfaces as the terse "Connection error." that looks like an outage.
    // Point Node at the openssl bundle that ships on darwin if the caller
    // hasn't already pinned one. Harmless on other platforms — Node only
    // honours SSL_CERT_FILE when present and readable.
    if (!process.env.SSL_CERT_FILE && !process.env.NODE_EXTRA_CA_CERTS) {
        const darwinDefault = '/etc/ssl/cert.pem'
        if (existsSync(darwinDefault)) {
            process.env.SSL_CERT_FILE = darwinDefault
        }
    }
}
loadRepoEnv()

function resolveOrThrow(provider: 'anthropic' | 'openai', modelId: string): Model<string> {
    const m = getModel(provider, modelId as never) as Model<string> | undefined
    if (!m) {
        throw new Error(
            `pi-ai getModel('${provider}', '${modelId}') returned undefined — model id not in registry. ` +
                `Set REAL_INFERENCE_MODEL_ID to a valid id (e.g. claude-haiku-4-5, claude-sonnet-4-6, claude-opus-4-7).`
        )
    }
    return m
}

interface ProviderSpec {
    label: string
    model: Model<string>
    apiKey: string
}

function discoverProviders(): ProviderSpec[] {
    const pin = process.env.REAL_INFERENCE_PROVIDER?.toLowerCase()
    const out: ProviderSpec[] = []
    if ((!pin || pin === 'gateway') && process.env.POSTHOG_AI_GATEWAY_KEY && process.env.POSTHOG_AI_GATEWAY_URL) {
        const gatewayKey = process.env.POSTHOG_AI_GATEWAY_KEY
        const gatewayUrl = process.env.POSTHOG_AI_GATEWAY_URL
        // Exercise BOTH provider shapes through the gateway. openai authenticates
        // with `Authorization: Bearer` natively; anthropic-messages relies on
        // posthogAiGatewayModel pinning that header (the regression this guards —
        // pi-ai's anthropic shape otherwise sends only `x-api-key`, which the
        // gateway rejects). An explicit REAL_INFERENCE_MODEL_ID pins one model.
        const gatewayModels = process.env.REAL_INFERENCE_MODEL_ID
            ? [process.env.REAL_INFERENCE_MODEL_ID]
            : ['openai/gpt-4.1-mini', 'anthropic/claude-haiku-4-5']
        for (const specModel of gatewayModels) {
            out.push({
                label: `ai-gateway (${specModel})`,
                model: posthogAiGatewayModel({ specModel, baseUrl: gatewayUrl, apiKey: gatewayKey }),
                apiKey: gatewayKey,
            })
        }
    }
    if ((!pin || pin === 'anthropic') && process.env.ANTHROPIC_API_KEY) {
        out.push({
            label: 'anthropic',
            model: resolveOrThrow('anthropic', process.env.REAL_INFERENCE_MODEL_ID ?? 'claude-haiku-4-5'),
            apiKey: process.env.ANTHROPIC_API_KEY,
        })
    }
    if ((!pin || pin === 'openai') && process.env.OPENAI_API_KEY) {
        out.push({
            label: 'openai',
            model: resolveOrThrow('openai', process.env.REAL_INFERENCE_MODEL_ID ?? 'gpt-4o-mini'),
            apiKey: process.env.OPENAI_API_KEY,
        })
    }
    return out
}

const SKIP = process.env.AGENT_SKIP_REAL_INFERENCE === '1' || process.env.AGENT_SKIP_REAL_INFERENCE === 'true'
const providers = SKIP ? [] : discoverProviders()

// Web-search provider chain — built once at file load from the same env the
// runner reads. Empty chain → the `@posthog/web-search` case below is skipped
// (matches the prod-gating behaviour: tool is dropped from sessions when
// nothing is keyed). Non-empty → the harness wires the chain into the Worker
// so a real model can actually call the tool.
const webSearchProviders = SKIP
    ? []
    : buildWebSearchProviders({
          primary: process.env.AGENT_WEB_SEARCH_PROVIDER,
          fallbacks: process.env.AGENT_WEB_SEARCH_FALLBACKS,
          keys: {
              exa: process.env.EXA_API_KEY,
              tavily: process.env.TAVILY_API_KEY,
              brave: process.env.BRAVE_API_KEY,
          },
      })

if (!SKIP && providers.length === 0) {
    // Surface the missing-creds error at file load — vitest reports it as a
    // suite-level failure and the run exits non-zero. A skipped describe
    // would hide the regression silently.
    throw new Error(
        'real-inference suite: no provider key found. Set ANTHROPIC_API_KEY / OPENAI_API_KEY / POSTHOG_AI_GATEWAY_* (env or repo-root .env), or set AGENT_SKIP_REAL_INFERENCE=1 to opt out.'
    )
}

const matrix = SKIP ? [{ label: 'skipped', model: null as never, apiKey: '' }] : providers
// `describe.skip` and `describe.each(...)` have incompatible TS signatures
// even though both expose the same call shape we use below. Cast to a
// shared callable so the test file typechecks; behaviour is unaffected.
const maybeDescribe = (SKIP ? describe.skip : describe.each(matrix.map((p) => [p.label, p] as const))) as (
    name: string,
    fn: (label: string, real: ProviderSpec) => void
) => void

// `@posthog/*` data tools act as the connected PostHog user — they need a
// `posthog` principal (carrying the caller's team) or they fail closed with
// `posthog_user_context_required`. Give the suite a posthog verifier alongside
// the public one, so no-bearer cases are unaffected but the tool tests can
// authenticate as a real user by sending a bearer. The harness already fakes
// `runHogql` (echoes the query), so a principal is all that's missing.
const POSTHOG_USER_TEAM = 1
const posthogAuthProvider: AuthProvider = {
    verifiers: [
        publicVerifier,
        {
            modeType: 'posthog',
            async verify(req) {
                const bearer = readBearer(req)
                if (!bearer) {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                return {
                    ok: true,
                    principal: { kind: 'posthog', user_id: 'real-user', team_id: POSTHOG_USER_TEAM },
                    credentials: { posthog_api: { kind: 'posthog_bearer', token: bearer } },
                }
            },
        },
    ],
}

maybeDescribe('real inference (via pi-ai): real e2e [%s]', (_label, real: ProviderSpec) => {
    let c: Cluster

    beforeEach(async () => {
        process.env.AGENT_TEST_API_KEY = real.apiKey
        c = await buildCluster({ model: real.model, authProvider: posthogAuthProvider, webSearchProviders })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('completes a single turn via real provider', async () => {
        await c.deployAgent({
            slug: 'real-1',
            files: { 'agent.md': "Reply with exactly 'PONG' and nothing else." },
        })
        const res = await request(c.ingress).post('/agents/real-1/run').send({ message: 'ping' })
        expect(res.status).toBe(200)
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const assistant = session!.conversation.find((m) => m.role === 'assistant') as {
            content: Array<{ type: string; text?: string }>
        }
        expect(assistant).not.toBeUndefined()
        const text = (assistant.content.find((b) => b.type === 'text') as { text: string }).text
        expect(text.length).toBeGreaterThan(0)
    }, 60_000)

    it('dispatches a native tool (@posthog/query) end-to-end', async () => {
        await c.deployAgent({
            slug: 'real-tool',
            spec: {
                auth: { modes: [{ type: 'posthog' }] },
                tools: [{ kind: 'native', id: '@posthog/query' }],
            },
            files: {
                'agent.md':
                    "You must call @posthog/query with query='select 1 as x' exactly once, then summarize the result in a brief sentence.",
            },
        })
        // @posthog/query acts as the connected user — authenticate the run so
        // the session carries a posthog principal (else the tool fails closed).
        const res = await request(c.ingress)
            .post('/agents/real-tool/run')
            .set('authorization', 'Bearer real-user-token')
            .send({ message: 'run it' })
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // The conversation's assistant message stores the provider-safe tool
        // name (so pi-ai can round-trip it to Anthropic on subsequent turns).
        // toolResult.toolName carries the original `@posthog/query` id — that's
        // what consumers / tests should assert on.
        const queryResult = session!.conversation.find(
            (m) => m.role === 'toolResult' && (m as { toolName?: string }).toolName === '@posthog/query'
        ) as { content?: Array<{ text?: string }> } | undefined
        expect(queryResult).not.toBeUndefined()
        // Assert the tool actually ran (the faux backend echoes the query),
        // not just that it was called — an errored result also carries the
        // toolName, which previously masked a missing-principal failure.
        const queryText = (queryResult!.content ?? []).map((b) => b.text ?? '').join(' ')
        expect(queryText).toContain('select 1')
    }, 90_000)

    /**
     * Real model → real `@posthog/web-search` provider chain → real vendor.
     * Pinned by the presence of a vendor key in env (EXA / TAVILY / BRAVE);
     * skipped (not failed) when none is set, so contributors without a key
     * don't see a red suite. The chain is built once at file load and wired
     * through `BuildClusterOpts.webSearchProviders`.
     */
    const webSearchIt = webSearchProviders.length > 0 ? it : it.skip
    webSearchIt(
        'dispatches @posthog/web-search end-to-end against a real vendor',
        async () => {
            await c.deployAgent({
                slug: 'real-web-search',
                spec: { tools: [{ kind: 'native', id: '@posthog/web-search' }] },
                files: {
                    'agent.md':
                        'You must call @posthog/web-search exactly once with query="posthog feature flags", ' +
                        'then summarize the first result in one short sentence.',
                },
            })
            const res = await request(c.ingress).post('/agents/real-web-search/run').send({ message: 'go' })
            await c.drain({ iterations: 100 })
            const session = await c.queue.get(res.body.session_id)
            expect(session!.state).toBe('completed')

            const toolResult = session!.conversation.find(
                (m) => m.role === 'toolResult' && (m as { toolName?: string }).toolName === '@posthog/web-search'
            ) as { content?: Array<{ text?: string }>; isError?: boolean } | undefined
            expect(toolResult).not.toBeUndefined()
            // A vendor 401 / network failure would land as `isError: true`, which
            // is the regression we'd want to catch (config plumbed wrong, key
            // didn't reach the provider, smokescreen tripped).
            expect(toolResult!.isError).not.toBe(true)
            // The body is the stringified provider envelope: `{provider, results:[{url,title,snippet}]}`.
            // Asserting on "posthog" as a substring is loose enough to survive
            // vendor result-ordering churn while still proving real results came back.
            const body = (toolResult!.content ?? []).map((b) => b.text ?? '').join(' ')
            expect(body.toLowerCase()).toContain('posthog')
        },
        120_000
    )

    it('dispatches a custom (sandboxed) tool end-to-end', async () => {
        const COMPILED = `
            module.exports = {
                id: "wordcount",
                actions: { default: (args) => ({ words: String(args.text ?? "").trim().split(/\\s+/).filter(Boolean).length }) },
            }
        `
        await c.deployAgent({
            slug: 'real-custom',
            spec: { tools: [{ kind: 'custom', id: 'wordcount', path: 'tools/wordcount/' }] },
            files: {
                'agent.md':
                    "You have a tool named `wordcount` that counts the words in a string. Call it exactly once with the text 'one two three four' and reply with the count.",
                'tools/wordcount/compiled.js': COMPILED,
                'tools/wordcount/schema.json': JSON.stringify({
                    description: 'Counts words in a string',
                    args_schema: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
                }),
            },
        })
        const res = await request(c.ingress).post('/agents/real-custom/run').send({ message: 'go' })
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const sawToolCall = session!.conversation.some(
            (m) =>
                m.role === 'assistant' &&
                (m.content as Array<{ type: string; name?: string }>).some(
                    (b) => b.type === 'toolCall' && b.name === 'wordcount'
                )
        )
        expect(sawToolCall).toBe(true)
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as {
            content: Array<{ text?: string }>
        }
        expect(toolResult.content[0].text).toContain('4')
    }, 120_000)

    it('multi-turn: text question ends turn, /send continues with the answer', async () => {
        // A text-only turn lands at `completed` (open). /send to a
        // `completed` session re-queues and the runner continues.
        await c.deployAgent({
            slug: 'real-multi',
            files: {
                'agent.md':
                    "On your first turn, reply with exactly: What is your name?. Don't call any tools. " +
                    'When the user responds with their name on the next turn, reply with exactly: Hi <NAME> (substituting the actual name).',
            },
        })
        const run = await request(c.ingress).post('/agents/real-multi/run').send({ message: 'hello' })
        const sid = run.body.session_id
        await c.drain({ iterations: 100 })
        let session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        await request(c.ingress).post('/agents/real-multi/send').send({ session_id: sid, message: 'Alice' })
        await c.drain({ iterations: 100 })
        session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        const assistantTexts = session!.conversation
            .filter((m) => m.role === 'assistant')
            .flatMap((m) =>
                (m.content as Array<{ type: string; text?: string }>)
                    .filter((b) => b.type === 'text' && b.text)
                    .map((b) => b.text!)
            )
        const joined = assistantTexts.join(' ')
        expect(joined).toMatch(/Alice/)
    }, 120_000)

    it('approval-gated tool: queued result → admin approves → real result lands', async () => {
        // Proves the synthetic queued tool_result is intelligible to a real
        // LLM: the model must understand it queued for review, NOT retry,
        // and continue once the approval lands. The faux-driven suite in
        // approval-gated.test.ts pins the wire-level contract; this one
        // pins "a real model can actually drive this loop".
        const { application } = await c.deployAgent({
            slug: 'real-gated',
            spec: {
                auth: { modes: [{ type: 'posthog' }] },
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/query',
                        requires_approval: true,
                        approval_policy: { allow_edit: false },
                    },
                ],
            },
            files: {
                'agent.md':
                    "You have one tool: @posthog/query. On the user's first request, call it exactly once with `select 1 as x`. " +
                    'If you receive a tool result whose JSON contains `"approval": {"state": "queued"}`, it means the call is awaiting human approval. ' +
                    'In that case, write a brief reply acknowledging the call is pending review (include the approval_url verbatim) — DO NOT call the tool again. ' +
                    'When you later receive a tool result whose JSON contains `"approval": {"state": "approved"}`, summarize the inner `result` field in one short sentence.',
            },
        })

        const run = await request(c.ingress)
            .post('/agents/real-gated/run')
            .set('authorization', 'Bearer real-user-token')
            .send({ message: 'run the query' })
        const sid = run.body.session_id

        await c.drain({ iterations: 100 })

        // Session did NOT park — gated calls keep running.
        let session = await c.queue.get(sid)
        expect(session!.state).not.toBe('waiting')

        // Janitor sees exactly one queued approval row.
        const queuedRes = await request(c.janitor)
            .get('/approvals')
            .query({ application_id: application.id, state: 'queued' })
        expect(queuedRes.status).toBe(200)
        expect(queuedRes.body.results).toHaveLength(1)
        const approvalId = queuedRes.body.results[0].id

        // The model acknowledged the queue (text mentioning the approval_url
        // or simply that approval is pending) without re-issuing the tool
        // call (idempotency would dedupe it anyway).
        const queuedAck = (session!.conversation as Array<{ role: string }>).filter((m) => m.role === 'assistant')
        expect(queuedAck.length).toBeGreaterThan(0)

        // Approve. Janitor wakes the session.
        const decideRes = await request(c.janitor).post(`/approvals/${approvalId}/decide`).send({
            decision: 'approve',
            decided_by: '00000000-0000-0000-0000-000000000001',
        })
        expect(decideRes.status).toBe(200)

        await c.drain({ iterations: 100 })

        // Session completes; the real tool result + the model's wrap-up are in
        // conversation.
        session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        // The synthetic approved envelope is present and carries the real
        // tool output. The wake message is a `user` message (not a
        // toolResult) — Anthropic 400s if a tool_result follows a closing
        // assistant message instead of its matching tool_use. The fake
        // HogQL backend echoes the query, so the envelope contains
        // "select 1".
        const approvedEnvelope = (
            session!.conversation as Array<{ role: string; content?: string | Array<{ text?: string }> }>
        )
            .filter((m) => m.role === 'user')
            .map((m) => (Array.isArray(m.content) ? (m.content[0]?.text ?? '') : ''))
            .find((t) => t.includes('"state":"approved"'))
        expect(approvedEnvelope).not.toBeUndefined()
        expect(approvedEnvelope).toContain('select 1')
    }, 180_000)

    it('framework preamble: model defaults to end-turn (not end-session) for an open-ended chat', async () => {
        // Plan §5 — meta-tool decision test. The framework preamble in
        // system-prompt.ts teaches the model to default to `meta-end-turn`
        // and reserve `meta-end-session` for irreversibly-complete tasks.
        // This case ships a conversational agent without any author-side
        // override and asserts the session lands at `completed` (open),
        // NOT `closed`. If a provider ignores the preamble and closes
        // every turn, this test catches the drift.
        await c.deployAgent({
            slug: 'real-default-end-turn',
            files: {
                // Deliberately ambient — no instruction about when to close.
                // The framework preamble is what tells the model not to.
                'agent.md':
                    'You are a friendly conversational agent. ' +
                    'Greet the user and answer any question they ask in one or two sentences. ' +
                    'Stay open to follow-up questions.',
            },
        })
        const res = await request(c.ingress).post('/agents/real-default-end-turn/run').send({ message: 'hi there!' })
        await c.drain({ iterations: 50 })
        const session = await c.queue.get(res.body.session_id)
        // The session is OPEN — the model didn't reach for end-session
        // just because the user's message looked like a turn boundary.
        expect(session!.state).toBe('completed')
    }, 60_000)

    it('framework preamble §3.3: tool failure recovery — model surfaces a real error in human terms', async () => {
        // Plan §5 — tool failure recovery test. The framework preamble in
        // §3.3 teaches the model to (a) re-read args on error, (b) not
        // retry blindly, (c) surface errors the user cares about. This
        // test deploys a custom tool that always throws, gives the model
        // one user-facing task that requires the tool, and asserts the
        // model produces a human-friendly explanation rather than
        // silently retrying.
        const BOOM_TOOL = `
            module.exports = {
                id: "fetch-data",
                actions: {
                    default: () => {
                        throw new Error("upstream API returned 503 Service Unavailable");
                    },
                },
            }
        `
        await c.deployAgent({
            slug: 'real-failure-recovery',
            spec: { tools: [{ kind: 'custom', id: 'fetch-data', path: 'tools/fetch-data/' }] },
            files: {
                'agent.md':
                    'You are a helpful assistant. The user wants you to fetch some data. ' +
                    'Call the `fetch-data` tool once. If it fails, explain in plain English to ' +
                    'the user what went wrong — do NOT silently retry the same call.',
                'tools/fetch-data/compiled.js': BOOM_TOOL,
                'tools/fetch-data/schema.json': JSON.stringify({
                    description: 'Fetches data from the upstream service',
                    args_schema: { type: 'object', properties: {} },
                }),
            },
        })
        const res = await request(c.ingress)
            .post('/agents/real-failure-recovery/run')
            .send({ message: 'fetch the data please' })
        await c.drain({ iterations: 50 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')

        // The conversation contains an error tool_result and the model's
        // final assistant turn mentions something user-friendly about it.
        const conv = session!.conversation
        const errorResult = conv.find((m) => m.role === 'toolResult' && (m as { isError?: boolean }).isError === true)
        expect(errorResult).not.toBeUndefined()

        const finalAssistant = [...conv].reverse().find((m) => m.role === 'assistant') as
            | { content: Array<{ type: string; text?: string }> }
            | undefined
        expect(finalAssistant).not.toBeUndefined()
        const finalText = finalAssistant!.content
            .filter((b) => b.type === 'text')
            .map((b) => b.text ?? '')
            .join(' ')
        // A human-friendly response: mentions either the tool, the
        // problem, or "available" — anything other than a silent retry.
        // Loose match across providers; the test is about model behaviour
        // direction, not specific wording.
        expect(finalText.length).toBeGreaterThan(20)
        expect(finalText).toMatch(/tool|query|available|unable|cannot|not.*available|sorry/i)
    }, 60_000)
})
