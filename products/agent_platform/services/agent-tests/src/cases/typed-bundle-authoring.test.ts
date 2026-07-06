/**
 * Typed bundle authoring API — full janitor e2e suite.
 *
 * Pins the typed bundle authoring API contract. Every test
 * here drives the real janitor HTTP surface against a real Postgres + real
 * S3 (SeaweedFS) via the harness — same impls prod runs.
 *
 * The cases below are the floor. Each represents either:
 *   - A real authoring flow the web app or Claude Code-style MCP performs.
 *   - A failure mode we've actually hit in production / past concierge
 *     sessions (broken tool shapes, spec drift, frozen-revision writes).
 *
 * If a case fails here, the feature is broken; we don't ship.
 */

import { readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import request from 'supertest'

import { AgentSpecSchema } from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Canonical "good" tool source — matches the AST shape the runner requires.
// Used as the baseline; tests that need bad shapes inline their own source.
const GOOD_TOOL_SOURCE = `
export default {
    actions: {
        default: async (args: { name?: string }) => ({ hello: args.name ?? 'world' }),
    },
}
`.trim()

// Spec defaults for a draft revision the typed endpoints will populate.
// The harness's createApplication + createRevision sit below deployAgent
// (which auto-freezes); we use them directly to keep the revision draft.
function defaultSpec(): Record<string, unknown> {
    return {
        models: { mode: 'manual', models: [{ model: 'faux/faux' }] },
        triggers: [
            { type: 'chat', config: {}, auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
        ],
    }
}

async function newDraft(c: Cluster, slug = 'tba-test'): Promise<string> {
    const app = await c.revisions.createApplication({
        team_id: 1,
        slug: `${slug}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
        name: slug,
        description: '',
    })
    const spec = AgentSpecSchema.parse(defaultSpec())
    const rev = await c.revisions.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: `s3://test/${app.id}/`,
        spec,
    })
    // Seed a default agent.md so freeze's validation can pass without the
    // test having to write one. Tests that explicitly set agent_md
    // overwrite this via PUT /agent_md.
    await c.bundle.write(rev.id, 'agent.md', '# default agent prompt')
    return rev.id
}

describe('typed bundle authoring API: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    // ─── Round-trip identity ─────────────────────────────────────────

    describe('GET /bundle on a fresh draft', () => {
        it('returns an empty typed shape (modulo the seeded agent.md)', async () => {
            const rid = await newDraft(c)
            const res = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            expect(res.status).toBe(200)
            // newDraft seeds a default agent.md so freeze can pass validate;
            // skills + tools start empty.
            expect(res.body.bundle.skills).toEqual([])
            expect(res.body.bundle.tools).toEqual([])
            expect(res.body.bundle.spec).toEqual(
                expect.objectContaining({
                    models: { mode: 'manual', models: [{ model: 'faux/faux' }], optimize_for: 'cost' },
                })
            )
            expect(res.body.warnings).toEqual([])
        })
    })

    describe('PUT /bundle full payload → GET /bundle round-trip', () => {
        it('round-trips agent_md/tools/spec and leaves skills (managed via /skills/<id>) intact', async () => {
            const rid = await newDraft(c)
            // Skills are store-backed now — authored via the single-resource
            // `/skills/<id>` PUT (and at freeze from `skill_refs`), never through
            // the full `/bundle` payload. Seed one to prove the full PUT below
            // doesn't manage or clobber it.
            await request(c.janitor).put(`/revisions/${rid}/skills/notify`).send({
                description: 'How to ping ops.',
                body: '# notify',
            })
            const payload = {
                agent_md: 'system prompt',
                tools: [
                    {
                        id: 'echo',
                        description: 'echo me',
                        args_schema: { type: 'object', properties: { msg: { type: 'string' } } },
                        source: GOOD_TOOL_SOURCE,
                    },
                ],
                spec: {
                    models: { mode: 'manual', models: [{ model: 'faux/faux' }] },
                    triggers: [
                        {
                            type: 'chat',
                            config: {},
                            auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                        },
                    ],
                },
            }
            const put = await request(c.janitor).put(`/revisions/${rid}/bundle`).send(payload)
            expect(put.status).toBe(200)

            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            expect(get.status).toBe(200)
            expect(get.body.bundle.agent_md).toBe('system prompt')
            expect(get.body.bundle.tools).toHaveLength(1)
            expect(get.body.bundle.tools[0].id).toBe('echo')
            // The skill set before the full PUT survives — `/bundle` doesn't own skills.
            expect(get.body.bundle.skills.map((s: { id: string }) => s.id)).toEqual(['notify'])
            const notify = get.body.bundle.skills.find((s: { id: string; body: string }) => s.id === 'notify')
            expect(notify.body).toBe('# notify')

            // Server-derived: tools/echo/compiled.js exists in the bundle.
            expect(await c.bundle.exists(rid, 'tools/echo/compiled.js')).toBe(true)
        })

        it('freezing twice on identical content produces the same sha256', async () => {
            const ridA = await newDraft(c, 'sha-a')
            const ridB = await newDraft(c, 'sha-b')
            const payload = {
                agent_md: 'identical',
                skills: [],
                tools: [],
                spec: defaultSpec(),
            }
            await request(c.janitor).put(`/revisions/${ridA}/bundle`).send(payload)
            await request(c.janitor).put(`/revisions/${ridB}/bundle`).send(payload)
            const freezeA = await request(c.janitor).post(`/revisions/${ridA}/freeze`)
            const freezeB = await request(c.janitor).post(`/revisions/${ridB}/freeze`)
            expect(freezeA.status).toBe(200)
            expect(freezeB.status).toBe(200)
            expect(freezeA.body.bundle_sha256).toBe(freezeB.body.bundle_sha256)
        })
    })

    // ─── Per-resource PUT semantics ──────────────────────────────────

    describe('single-resource PUTs leave siblings untouched', () => {
        it('PUT /skills/foo only modifies foo', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/skills/research`).send({
                description: 'first',
                body: 'first body',
            })
            await request(c.janitor).put(`/revisions/${rid}/skills/triage`).send({
                description: 'triage',
                body: 'triage body',
            })
            // Update research only.
            await request(c.janitor).put(`/revisions/${rid}/skills/research`).send({
                description: 'second',
                body: 'updated body',
            })
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            const research = get.body.bundle.skills.find((s: { id: string }) => s.id === 'research')
            const triage = get.body.bundle.skills.find((s: { id: string }) => s.id === 'triage')
            expect(research.body).toBe('updated body')
            expect(triage.body).toBe('triage body')
        })

        it('PUT /tools/foo regenerates compiled.js when source changes', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/tools/hello`).send({
                description: 'hello',
                args_schema: {},
                source: GOOD_TOOL_SOURCE,
            })
            const compiledV1 = await c.bundle.readText(rid, 'tools/hello/compiled.js')
            await request(c.janitor)
                .put(`/revisions/${rid}/tools/hello`)
                .send({
                    description: 'hello',
                    args_schema: {},
                    source: GOOD_TOOL_SOURCE.replace('world', 'planet'),
                })
            const compiledV2 = await c.bundle.readText(rid, 'tools/hello/compiled.js')
            expect(compiledV2).not.toBe(compiledV1)
            expect(compiledV2).toContain('planet')
        })

        it('PUT /agent_md only changes agent_md', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/skills/x`).send({
                description: 'x',
                body: 'x body',
            })
            await request(c.janitor).put(`/revisions/${rid}/agent_md`).send({ content: 'updated prompt' })
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            expect(get.body.bundle.agent_md).toBe('updated prompt')
            expect(get.body.bundle.skills.map((s: { id: string }) => s.id)).toEqual(['x'])
        })

        it('PUT /spec only changes spec; skills + tools preserved', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/skills/x`).send({
                description: 'x',
                body: 'x body',
            })
            await request(c.janitor).put(`/revisions/${rid}/tools/t`).send({
                description: 't',
                args_schema: {},
                source: GOOD_TOOL_SOURCE,
            })
            const newSpec = {
                ...defaultSpec(),
                models: { mode: 'manual', models: [{ model: 'faux/changed' }] },
            }
            const put = await request(c.janitor).put(`/revisions/${rid}/spec`).send({ spec: newSpec })
            expect(put.status).toBe(200)
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            expect(get.body.bundle.spec.models).toEqual({
                mode: 'manual',
                models: [{ model: 'faux/changed' }],
                optimize_for: 'cost',
            })
            expect(get.body.bundle.skills).toHaveLength(1)
            expect(get.body.bundle.tools).toHaveLength(1)
        })
    })

    // ─── DELETE semantics ─────────────────────────────────────────────

    describe('DELETE removes a resource cleanly', () => {
        it('DELETE /skills/foo strips the skill folder from S3', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/skills/research`).send({
                description: 'research',
                body: 'research body',
            })
            const del = await request(c.janitor).delete(`/revisions/${rid}/skills/research`)
            expect(del.status).toBe(200)
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            expect(get.body.bundle.skills).toEqual([])
            expect(await c.bundle.exists(rid, 'skills/research/SKILL.md')).toBe(false)
            expect(await c.bundle.list(rid, 'skills/research/')).toEqual([])
        })

        it('DELETE /tools/foo strips source.ts + compiled.js + schema.json', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/tools/t`).send({
                description: 't',
                args_schema: {},
                source: GOOD_TOOL_SOURCE,
            })
            const del = await request(c.janitor).delete(`/revisions/${rid}/tools/t`)
            expect(del.status).toBe(200)
            for (const path of ['tools/t/source.ts', 'tools/t/compiled.js', 'tools/t/schema.json']) {
                expect(await c.bundle.exists(rid, path), path).toBe(false)
            }
        })

        it('DELETE of non-existent resource returns 404', async () => {
            const rid = await newDraft(c)
            const r1 = await request(c.janitor).delete(`/revisions/${rid}/skills/ghost`)
            expect(r1.status).toBe(404)
            expect(r1.body.error).toBe('skill_not_found')
            const r2 = await request(c.janitor).delete(`/revisions/${rid}/tools/ghost`)
            expect(r2.status).toBe(404)
            expect(r2.body.error).toBe('tool_not_found')
        })

        it('after DELETE + freeze, the derived spec does not reference the deleted resource', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/skills/keep`).send({
                description: 'k',
                body: '# k',
            })
            await request(c.janitor).put(`/revisions/${rid}/skills/gone`).send({
                description: 'g',
                body: '# g',
            })
            await request(c.janitor).delete(`/revisions/${rid}/skills/gone`)
            const freeze = await request(c.janitor).post(`/revisions/${rid}/freeze`)
            expect(freeze.status).toBe(200)
            const rev = await c.revisions.getRevision(rid)
            expect(rev!.spec.skills.map((s) => s.id)).toEqual(['keep'])
        })
    })

    // ─── Full-replace PUT /bundle ────────────────────────────────────

    describe('PUT /bundle is a true full replace', () => {
        it('a full /bundle replace does NOT manage skills — they are owned by /skills/<id> + freeze', async () => {
            const rid = await newDraft(c)
            for (const id of ['a', 'b', 'c']) {
                await request(c.janitor)
                    .put(`/revisions/${rid}/skills/${id}`)
                    .send({
                        description: id,
                        body: `# ${id}`,
                    })
            }
            // A full replace that omits skills (the only shape the PUT body accepts —
            // `skills` was dropped from the payload schema). Skills are NOT swept by
            // this; they are store-backed and only freeze reconciles them to skill_refs.
            await request(c.janitor).put(`/revisions/${rid}/bundle`).send({
                agent_md: 'top',
                tools: [],
                spec: defaultSpec(),
            })
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            const ids = get.body.bundle.skills.map((s: { id: string }) => s.id).sort()
            expect(ids).toEqual(['a', 'b', 'c'])
            expect(await c.bundle.exists(rid, 'skills/b/SKILL.md')).toBe(true)
            expect(await c.bundle.exists(rid, 'skills/c/SKILL.md')).toBe(true)
        })

        it('tools not in payload are deleted (source + compiled + schema)', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/tools/keep`).send({
                description: 'k',
                args_schema: {},
                source: GOOD_TOOL_SOURCE,
            })
            await request(c.janitor).put(`/revisions/${rid}/tools/gone`).send({
                description: 'g',
                args_schema: {},
                source: GOOD_TOOL_SOURCE,
            })
            await request(c.janitor)
                .put(`/revisions/${rid}/bundle`)
                .send({
                    agent_md: '',
                    skills: [],
                    tools: [
                        {
                            id: 'keep',
                            description: 'k',
                            args_schema: {},
                            source: GOOD_TOOL_SOURCE,
                        },
                    ],
                    spec: defaultSpec(),
                })
            for (const p of ['tools/gone/source.ts', 'tools/gone/compiled.js', 'tools/gone/schema.json']) {
                expect(await c.bundle.exists(rid, p), p).toBe(false)
            }
            expect(await c.bundle.exists(rid, 'tools/keep/compiled.js')).toBe(true)
        })
    })

    // ─── Tool upload pipeline (AST + compile) ────────────────────────

    describe('PUT /tools/:id runs AST check + esbuild', () => {
        it('valid source stamps compiled.js + schema.json', async () => {
            const rid = await newDraft(c)
            const res = await request(c.janitor)
                .put(`/revisions/${rid}/tools/ok`)
                .send({
                    description: 'ok',
                    args_schema: { type: 'object' },
                    source: GOOD_TOOL_SOURCE,
                })
            expect(res.status).toBe(200)
            const compiled = await c.bundle.readText(rid, 'tools/ok/compiled.js')
            expect(compiled).toContain('exports')
            const schemaText = await c.bundle.readText(rid, 'tools/ok/schema.json')
            const schema = JSON.parse(schemaText) as Record<string, unknown>
            expect(schema.description).toBe('ok')
            expect(schema.args_schema).toEqual({ type: 'object' })
        })

        it.each([
            {
                label: 'bare function default',
                source: 'export default async function run() { return {} }',
                code: 'ast_default_not_object',
            },
            { label: 'object missing actions', source: 'export default { id: "x" }', code: 'ast_missing_actions' },
            {
                label: 'actions.default not callable',
                source: 'export default { actions: { default: "nope" } }',
                code: 'ast_default_action_not_callable',
            },
            {
                label: 'dynamic factory export',
                source: 'function f() { return { actions: { default: () => ({}) } } }\nexport default f()',
                code: 'ast_dynamic_export',
            },
        ])('rejects $label and leaves the bundle untouched', async ({ source, code }) => {
            const rid = await newDraft(c)
            const res = await request(c.janitor).put(`/revisions/${rid}/tools/bad`).send({
                description: 'bad',
                args_schema: {},
                source,
            })
            expect(res.status).toBe(422)
            expect(res.body.error).toBe('tool_compile_failed')
            expect(res.body.errors[0].kind).toBe(code)
            expect(await c.bundle.exists(rid, 'tools/bad/source.ts')).toBe(false)
            expect(await c.bundle.exists(rid, 'tools/bad/compiled.js')).toBe(false)
        })

        it('rejects invalid args_schema (not an object)', async () => {
            const rid = await newDraft(c)
            const res = await request(c.janitor).put(`/revisions/${rid}/tools/bad`).send({
                description: 'bad',
                args_schema: 'not an object',
                source: GOOD_TOOL_SOURCE,
            })
            expect(res.status).toBe(400)
            expect(res.body.error).toBe('invalid_request')
        })

        it('rejects tool ids that fail the resource-id regex', async () => {
            const rid = await newDraft(c)
            const res = await request(c.janitor).put(`/revisions/${rid}/tools/BadID`).send({
                description: 'x',
                args_schema: {},
                source: GOOD_TOOL_SOURCE,
            })
            expect(res.status).toBe(400)
            expect(res.body.error).toBe('invalid_resource_id')
        })
    })

    // ─── Spec derivation at freeze ───────────────────────────────────

    describe('freeze derives spec.skills / spec.tools from the typed bundle', () => {
        it('drafts have empty arrays; freeze populates them in id order', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/skills/zebra`).send({
                description: 'z',
                body: '# z',
            })
            await request(c.janitor).put(`/revisions/${rid}/skills/alpha`).send({
                description: 'a',
                body: '# a',
            })
            await request(c.janitor).put(`/revisions/${rid}/tools/echo`).send({
                description: 'e',
                args_schema: {},
                source: GOOD_TOOL_SOURCE,
            })

            // Draft spec has nothing yet.
            const beforeFreeze = await c.revisions.getRevision(rid)
            expect(beforeFreeze!.spec.skills).toEqual([])
            expect(beforeFreeze!.spec.tools).toEqual([])

            const freeze = await request(c.janitor).post(`/revisions/${rid}/freeze`)
            expect(freeze.status).toBe(200)

            // After freeze, spec carries derived entries.
            const after = await c.revisions.getRevision(rid)
            expect(after!.spec.skills.map((s) => s.id).sort()).toEqual(['alpha', 'zebra'])
            const echo = after!.spec.tools.find((t) => 'id' in t && t.id === 'echo')
            expect(echo).not.toBeUndefined()
            expect(echo!.kind).toBe('custom')
        })

        it('preserves author-written native + client tools alongside derived custom tools', async () => {
            const rid = await newDraft(c)
            await request(c.janitor)
                .put(`/revisions/${rid}/spec`)
                .send({
                    spec: {
                        ...defaultSpec(),
                        triggers: [
                            {
                                type: 'chat',
                                config: {},
                                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                            },
                        ],
                    },
                })
            // Set spec.tools[] explicitly via the legacy AgentSpec shape on
            // updateSpec; the typed PUT /spec strips skills/tools but
            // updateSpec lets us seed a native tool for the merge test.
            const current = await c.revisions.getRevision(rid)
            const specWithNative = AgentSpecSchema.parse({
                ...current!.spec,
                tools: [{ kind: 'native', id: '@posthog/http-request' }],
            })
            await c.revisions.updateSpec(rid, specWithNative)

            await request(c.janitor).put(`/revisions/${rid}/tools/custom1`).send({
                description: 'c',
                args_schema: {},
                source: GOOD_TOOL_SOURCE,
            })
            await request(c.janitor).post(`/revisions/${rid}/freeze`)
            const after = await c.revisions.getRevision(rid)
            const ids = after!.spec.tools.map((t) => ('id' in t ? t.id : ''))
            expect(ids).toContain('@posthog/http-request')
            expect(ids).toContain('custom1')
        })
    })

    // ─── Lifecycle ──────────────────────────────────────────────────

    describe('draft → ready lifecycle', () => {
        it('PUT against a frozen revision returns 409', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/agent_md`).send({ content: 'x' })
            await request(c.janitor).post(`/revisions/${rid}/freeze`)
            const r = await request(c.janitor).put(`/revisions/${rid}/agent_md`).send({ content: 'y' })
            expect(r.status).toBe(409)
            expect(r.body.error).toBe('revision_not_draft')
        })

        it('PUT against a non-existent revision returns 404', async () => {
            const fakeId = '00000000-0000-0000-0000-000000000000'
            const r = await request(c.janitor).put(`/revisions/${fakeId}/agent_md`).send({ content: 'x' })
            expect(r.status).toBe(404)
            expect(r.body.error).toBe('revision_not_found')
        })

        it('GET /bundle works on ready revisions too (read-only)', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/agent_md`).send({ content: 'sealed' })
            await request(c.janitor).post(`/revisions/${rid}/freeze`)
            await c.revisions.setRevisionState(rid, 'ready', '0'.repeat(64))
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            expect(get.status).toBe(200)
            expect(get.body.bundle.agent_md).toBe('sealed')
        })
    })

    // ─── Full lifecycle: build → validate → freeze → assert S3 ────

    describe('full lifecycle: typed PUTs → validate → freeze → assert canonical S3 layout', () => {
        it('lays down every canonical bundle file the runner expects to read', async () => {
            const rid = await newDraft(c, 'lifecycle')

            // 1. Replace the default agent.md with a known body.
            const agentMd = '# Hedgebox helper\n\nYou are a helpful assistant.'
            const r1 = await request(c.janitor).put(`/revisions/${rid}/agent_md`).send({ content: agentMd })
            expect(r1.status).toBe(200)

            // 2. Push two skills.
            const r2 = await request(c.janitor).put(`/revisions/${rid}/skills/research`).send({
                description: 'When to deep-dive.',
                body: '# research\nDo your homework.',
            })
            expect(r2.status).toBe(200)
            const r3 = await request(c.janitor).put(`/revisions/${rid}/skills/triage`).send({
                description: 'Initial triage.',
                body: '# triage\nFirst 5 minutes.',
            })
            expect(r3.status).toBe(200)

            // 3. Push two custom tools — each runs the AST shape check + esbuild.
            const echoSrc = `
export default {
    actions: {
        default: async (args: { msg: string }) => ({ echoed: args.msg }),
    },
}
`.trim()
            const incrSrc = `
export default {
    actions: {
        default: async (args: { n: number }) => ({ next: args.n + 1 }),
    },
}
`.trim()
            const r4 = await request(c.janitor)
                .put(`/revisions/${rid}/tools/echo`)
                .send({
                    description: 'Echo input.',
                    args_schema: { type: 'object', properties: { msg: { type: 'string' } } },
                    source: echoSrc,
                })
            expect(r4.status).toBe(200)
            const r5 = await request(c.janitor)
                .put(`/revisions/${rid}/tools/incr`)
                .send({
                    description: 'Increment a number.',
                    args_schema: { type: 'object', properties: { n: { type: 'number' } } },
                    source: incrSrc,
                })
            expect(r5.status).toBe(200)

            // 4. Validate — passes on the draft even though spec.skills/tools
            //    are still empty (the freeze step is what derives them).
            const validate = await request(c.janitor).post(`/revisions/${rid}/validate`)
            expect(validate.status).toBe(200)
            expect(validate.body.ok).toBe(true)
            expect(validate.body.errors).toEqual([])

            // 5. Freeze — derives spec.skills/tools + writes the .frozen marker.
            const freeze = await request(c.janitor).post(`/revisions/${rid}/freeze`)
            expect(freeze.status).toBe(200)
            expect(freeze.body.bundle_sha256).toMatch(/^[0-9a-f]{64}$/)

            // 6. Assert the canonical S3 layout — every path the runner will
            //    walk at session start is present with the expected content.
            const expectedAgentMd = await c.bundle.readText(rid, 'agent.md')
            expect(expectedAgentMd).toBe(agentMd)

            // Each skill body lands at the canonical `skills/<id>/SKILL.md`.
            const researchBody = await c.bundle.readText(rid, 'skills/research/SKILL.md')
            expect(researchBody).toBe('# research\nDo your homework.')

            const triageBody = await c.bundle.readText(rid, 'skills/triage/SKILL.md')
            expect(triageBody).toBe('# triage\nFirst 5 minutes.')
            // The skill folder holds exactly the one SKILL.md — no other files.
            const triageEntries = await c.bundle.list(rid, 'skills/triage/')
            expect(triageEntries.map((e) => e.path)).toEqual(['skills/triage/SKILL.md'])

            for (const id of ['echo', 'incr']) {
                const src = await c.bundle.readText(rid, `tools/${id}/source.ts`)
                expect(src).toContain('actions:')
                expect(src).toContain('default:')

                const compiled = await c.bundle.readText(rid, `tools/${id}/compiled.js`)
                // CJS = exports.default-style, NOT the original `export default { ... }`.
                expect(compiled).toMatch(/exports/)
                expect(compiled).not.toContain('export default {')

                const schemaText = await c.bundle.readText(rid, `tools/${id}/schema.json`)
                const schema = JSON.parse(schemaText) as Record<string, unknown>
                expect(schema.description).toBeTruthy()
                expect(schema.args_schema).toMatchObject({ type: 'object' })
            }

            // 7. Assert the derived spec entries match the bundle contents.
            const rev = await c.revisions.getRevision(rid)
            expect(
                rev!.spec.skills.map((s) => ({ id: s.id, path: s.path })).sort((a, b) => a.id.localeCompare(b.id))
            ).toEqual([
                { id: 'research', path: 'skills/research/SKILL.md' },
                { id: 'triage', path: 'skills/triage/SKILL.md' },
            ])
            // Custom tool entries appear with kind:'custom' alongside any
            // native/client tools the spec carries.
            const customTools = rev!.spec.tools.filter(
                (t): t is Extract<typeof t, { kind: 'custom' }> => t.kind === 'custom'
            )
            expect(
                customTools.map((t) => ({ id: t.id, path: t.path })).sort((a, b) => a.id.localeCompare(b.id))
            ).toEqual([
                { id: 'echo', path: 'tools/echo' },
                { id: 'incr', path: 'tools/incr' },
            ])

            // 8. The .frozen marker is set; further writes return 409.
            expect(await c.bundle.isFrozen(rid)).toBe(true)
            const blocked = await request(c.janitor).put(`/revisions/${rid}/agent_md`).send({ content: 'late' })
            expect(blocked.status).toBe(409)
        })
    })

    // ─── Multi-author safety ────────────────────────────────────────

    describe('multiple writes interleaved', () => {
        it('per-resource PUTs in parallel each land without stomping the other', async () => {
            const rid = await newDraft(c)
            // Two clients writing different resources concurrently.
            await Promise.all([
                request(c.janitor).put(`/revisions/${rid}/skills/foo`).send({
                    description: 'foo',
                    body: '# foo',
                }),
                request(c.janitor).put(`/revisions/${rid}/tools/bar`).send({
                    description: 'bar',
                    args_schema: {},
                    source: GOOD_TOOL_SOURCE,
                }),
            ])
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            expect(get.body.bundle.skills.map((s: { id: string }) => s.id)).toEqual(['foo'])
            expect(get.body.bundle.tools.map((t: { id: string }) => t.id)).toEqual(['bar'])
        })

        it('two PUTs of the same skill — last-write-wins', async () => {
            const rid = await newDraft(c)
            await request(c.janitor).put(`/revisions/${rid}/skills/x`).send({
                description: 'first',
                body: 'first body',
            })
            await request(c.janitor).put(`/revisions/${rid}/skills/x`).send({
                description: 'second',
                body: 'second body',
            })
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            const x = get.body.bundle.skills.find((s: { id: string }) => s.id === 'x')
            expect(x.body).toBe('second body')
        })
    })

    // ─── Example bundle ↔ SKILL.md storage contract ──────────────────
    // Guards the convention every example agent follows: skills authored as
    // `skills/<id>/SKILL.md` on disk are accepted by the typed API, stored at
    // exactly that canonical path in S3, and read back intact via GET /bundle.
    // Runs against a real example bundle (sre-slack-bot) so a drift between
    // the on-disk layout and the platform storage format fails here.
    describe('example bundle skills round-trip through the SKILL.md storage contract', () => {
        it('accepts sre-slack-bot skills via the API, stores them at skills/<id>/SKILL.md, loads them back', async () => {
            const exampleRoot = resolve(__dirname, '../examples/sre-slack-bot')
            const spec = JSON.parse(await readFile(join(exampleRoot, 'spec.json'), 'utf-8')) as {
                skills: Array<{ id: string; description: string; path: string }>
            }
            // Load each skill body from its on-disk `skills/<id>/SKILL.md`.
            const skills = await Promise.all(
                spec.skills.map(async (s) => {
                    expect(s.path).toBe(`skills/${s.id}/SKILL.md`) // the convention itself
                    return {
                        id: s.id,
                        description: s.description,
                        body: await readFile(join(exampleRoot, s.path), 'utf-8'),
                    }
                })
            )
            expect(skills.length).toBeGreaterThan(0)

            const rid = await newDraft(c, 'sre-roundtrip')

            // 1. ACCEPTED — each skill is authored through the single-resource
            //    `/skills/<id>` PUT (the store-backed authoring path; the full
            //    `/bundle` payload no longer carries skills).
            for (const s of skills) {
                const put = await request(c.janitor)
                    .put(`/revisions/${rid}/skills/${s.id}`)
                    .send({ description: s.description, body: s.body })
                expect(put.status).toBe(200)
            }

            // 2. STORED — each body lands at exactly `skills/<id>/SKILL.md` in S3.
            for (const s of skills) {
                expect(await c.bundle.exists(rid, `skills/${s.id}/SKILL.md`)).toBe(true)
                expect(await c.bundle.readText(rid, `skills/${s.id}/SKILL.md`)).toBe(s.body)
            }

            // 3. LOADED — GET /bundle reconstructs the typed skills with bodies intact.
            const get = await request(c.janitor).get(`/revisions/${rid}/bundle`)
            expect(get.status).toBe(200)
            const loaded = get.body.bundle.skills as Array<{ id: string; body: string }>
            expect(loaded.map((s) => s.id).sort()).toEqual(skills.map((s) => s.id).sort())
            for (const s of skills) {
                expect(loaded.find((l) => l.id === s.id)!.body).toBe(s.body)
            }
        })
    })
})
