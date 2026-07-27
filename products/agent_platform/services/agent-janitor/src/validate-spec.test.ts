import type { S3Client } from '@aws-sdk/client-s3'
import { z } from 'zod'

import {
    AgentRevision,
    AgentSpecSchema,
    buildTestBundleStore,
    type CatalogModel,
    newTestPrefix,
    S3BundleStore,
    wipeTestPrefix,
} from '@posthog/agent-shared'

import { validateRevisionBundle } from './validate-spec'

let bundlePrefix: string
let bundleClient: S3Client
let bundleStore: S3BundleStore

beforeEach(() => {
    bundlePrefix = newTestPrefix('agent_bundles_validate_spec_test')
    const built = buildTestBundleStore(bundlePrefix)
    bundleClient = built.client
    bundleStore = built.store
})

afterEach(async () => {
    await wipeTestPrefix(bundleClient, bundlePrefix).catch(() => undefined)
    bundleClient.destroy()
})

function makeBundles(): S3BundleStore {
    return bundleStore
}

// Default fixture has a `chat` trigger so every test isn't forced to declare
// one. The `no_triggers` rule is exercised explicitly below by passing
// `triggers: []`.
function mkRev(spec: Partial<z.input<typeof AgentSpecSchema>> = {}): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app1',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-05-27',
        state: 'draft',
        bundle_uri: 'mem://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({
            models: { mode: 'manual', models: [{ model: 'anthropic/claude-haiku-4-5' }] },
            triggers: [
                { type: 'chat', config: {}, auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
            ],
            ...spec,
        }),
        encrypted_env: null,
    }
}

describe('validateRevisionBundle', () => {
    it('passes when the bundle has the entrypoint and no tools/skills are declared', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(mkRev(), bundles)
        expect(report.ok).toBe(true)
        expect(report.errors).toEqual([])
        expect(report.resolved_natives).toEqual([])
    })

    it('flags a manual model the gateway does not serve; passes one it does', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const catalog: CatalogModel[] = [
            {
                canonical: 'anthropic/claude-haiku-4.5',
                id: 'claude-haiku-4-5-20251001',
                aliases: ['claude-haiku-4-5'],
                owned_by: 'anthropic',
                context_window: 200_000,
                pricing: { prompt: 0.000001, completion: 0.000005 },
            },
        ]
        const bad = mkRev({ models: { mode: 'manual', models: [{ model: 'openai/gpt-nope' }] } })
        const badReport = await validateRevisionBundle(bad, bundles, catalog)
        expect(badReport.ok).toBe(false)
        expect(badReport.errors).toContainEqual(
            expect.objectContaining({ code: 'invalid_model', pointer: 'spec.models.models[0].model' })
        )
        // the default rev's haiku model resolves against this catalog
        const good = await validateRevisionBundle(mkRev(), bundles, catalog)
        expect(good.errors.filter((e) => e.code === 'invalid_model')).toEqual([])
    })

    it('fails open on the model check when no catalog is supplied', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const rev = mkRev({ models: { mode: 'manual', models: [{ model: 'made/up' }] } })
        const report = await validateRevisionBundle(rev, bundles)
        expect(report.errors.filter((e) => e.code === 'invalid_model')).toEqual([])
    })

    it('reports missing_entrypoint when agent.md is absent', async () => {
        const bundles = makeBundles()
        const report = await validateRevisionBundle(mkRev(), bundles)
        expect(report.ok).toBe(false)
        expect(report.errors).toEqual([
            { code: 'missing_entrypoint', message: expect.stringContaining('agent.md'), pointer: 'agent.md' },
        ])
    })

    it('catches unknown native tool ids and resolves valid ones', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(
            mkRev({
                tools: [
                    { kind: 'native', id: '@posthog/query' },
                    { kind: 'native', id: '@posthog/does-not-exist' },
                ],
            }),
            bundles
        )
        expect(report.resolved_natives).toEqual(['@posthog/query'])
        expect(report.errors).toEqual([
            {
                code: 'unknown_native_tool',
                message: expect.stringContaining('@posthog/does-not-exist'),
                pointer: 'spec.tools[1].id',
            },
        ])
    })

    // Tool / skill bundle-presence checks were deleted alongside the typed
    // bundle authoring API rollout. Authors no
    // longer write paths; `spec.tools[]` and `spec.skills[]` are server-
    // derived at freeze from the typed resources in the bundle, so a
    // dangling reference is structurally impossible. The legacy tests
    // (missing_custom_tool_source, missing_custom_tool_schema,
    // invalid_custom_tool_source, missing_skill, orphan_custom_tool_dir,
    // orphan_skill_file) are gone with the codes they covered.

    it('reports no_triggers when spec.triggers is empty', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(mkRev({ triggers: [] }), bundles)
        expect(report.ok).toBe(false)
        expect(report.errors).toEqual([
            {
                code: 'no_triggers',
                message: expect.stringContaining('no entry points'),
                pointer: 'spec.triggers',
            },
        ])
    })

    it('returns revision state alongside the report', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const rev = mkRev()
        rev.state = 'ready'
        const report = await validateRevisionBundle(rev, bundles)
        expect(report.revision_state).toBe('ready')
        expect(report.revision_id).toBe('rev1')
    })

    describe('cron triggers', () => {
        const cronTrigger = (
            overrides: Record<string, unknown> = {}
        ): NonNullable<z.input<typeof AgentSpecSchema>['triggers']>[number] => ({
            type: 'cron',
            config: {
                name: 'digest',
                schedule: '0 9 * * MON',
                prompt: 'Produce the weekly digest for {fired_at:date}.',
                ...overrides,
            },
        })

        async function setup(
            triggers: Array<NonNullable<z.input<typeof AgentSpecSchema>['triggers']>[number]>
        ): ReturnType<typeof validateRevisionBundle> {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            return validateRevisionBundle(mkRev({ triggers }), bundles)
        }

        it('passes a well-formed cron trigger', async () => {
            const report = await setup([cronTrigger()])
            expect(report.ok).toBe(true)
            expect(report.errors).toEqual([])
        })

        it('flags a malformed cron schedule', async () => {
            const report = await setup([cronTrigger({ schedule: '0 25 * * MON' })])
            const codes = report.errors.map((e) => e.code)
            expect(codes).toContain('invalid_cron_schedule')
        })

        it('flags a sub-minute schedule that fires more than once a minute', async () => {
            const report = await setup([cronTrigger({ schedule: '* * * * * *' })])
            const codes = report.errors.map((e) => e.code)
            expect(codes).toContain('cron_schedule_too_frequent')
        })

        it('accepts an every-minute schedule (the 60s boundary)', async () => {
            const report = await setup([cronTrigger({ schedule: '* * * * *' })])
            const codes = report.errors.map((e) => e.code)
            expect(codes).not.toContain('cron_schedule_too_frequent')
        })

        it('flags an unknown IANA timezone', async () => {
            const report = await setup([cronTrigger({ timezone: 'Mars/Olympus_Mons' })])
            const codes = report.errors.map((e) => e.code)
            expect(codes).toContain('invalid_cron_timezone')
        })

        it('accepts a known IANA timezone with DST', async () => {
            const report = await setup([cronTrigger({ timezone: 'US/Pacific' })])
            expect(report.ok).toBe(true)
        })

        it('flags duplicate cron names within the same triggers[]', async () => {
            const report = await setup([
                cronTrigger({ name: 'digest', schedule: '0 9 * * MON' }),
                cronTrigger({ name: 'digest', schedule: '0 9 * * FRI' }),
            ])
            const codes = report.errors.map((e) => e.code)
            expect(codes).toContain('duplicate_cron_name')
        })

        it('flags an unknown placeholder in the prompt', async () => {
            const report = await setup([cronTrigger({ prompt: 'Run the digest for {unknown_placeholder}.' })])
            const err = report.errors.find((e) => e.code === 'unknown_cron_placeholder')
            expect(err).not.toBeUndefined()
            expect(err?.message).toContain('unknown_placeholder')
            expect(err?.pointer).toBe('spec.triggers[0].config.prompt')
        })

        it('flags an unknown placeholder in external_key', async () => {
            const report = await setup([cronTrigger({ external_key: 'digest-{run_id}' })])
            const err = report.errors.find((e) => e.code === 'unknown_cron_placeholder')
            expect(err).not.toBeUndefined()
            expect(err?.message).toContain('run_id')
            expect(err?.pointer).toBe('spec.triggers[0].config.external_key')
        })

        it('accepts every whitelisted placeholder', async () => {
            const report = await setup([
                cronTrigger({
                    prompt: 'cron={cron_name} schedule={schedule} iso={fired_at:iso} date={fired_at:date} week={fired_at:week}',
                    external_key: 'k-{fired_at:week}-{cron_name}',
                }),
            ])
            expect(report.ok).toBe(true)
        })
    })

    describe('secret host binding', () => {
        it('flags ${NAME} in agent.md when the secret is declared as a bare string', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'Call slack with `Authorization: Bearer ${SLACK_BOT_TOKEN}`.')
            const report = await validateRevisionBundle(mkRev({ secrets: ['SLACK_BOT_TOKEN'] }), bundles)
            expect(report.ok).toBe(false)
            expect(report.errors).toEqual([
                {
                    code: 'secret_no_host_binding',
                    pointer: 'agent.md',
                    message: expect.stringContaining('SLACK_BOT_TOKEN'),
                },
            ])
        })

        it('flags ${NAME} in a declared skill body', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'see the skill')
            await bundles.write('rev1', 'skills/slack/SKILL.md', 'POST with `Bearer ${SLACK_BOT_TOKEN}`.')
            const report = await validateRevisionBundle(
                mkRev({
                    secrets: ['SLACK_BOT_TOKEN'],
                    skills: [
                        {
                            id: 'slack',
                            path: 'skills/slack/SKILL.md',
                            description: 'How to call Slack.',
                        },
                    ],
                }),
                bundles
            )
            expect(report.ok).toBe(false)
            expect(report.errors).toEqual([
                {
                    code: 'secret_no_host_binding',
                    pointer: 'spec.skills[0].path',
                    message: expect.stringContaining('SLACK_BOT_TOKEN'),
                },
            ])
        })

        it('accepts ${NAME} when the secret is in object form with allowed_hosts', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'Auth: `Bearer ${SLACK_BOT_TOKEN}`.')
            const report = await validateRevisionBundle(
                mkRev({ secrets: [{ name: 'SLACK_BOT_TOKEN', allowed_hosts: ['slack.com'] }] }),
                bundles
            )
            expect(report.ok).toBe(true)
        })

        it('does NOT flag a bare-string secret that is not referenced as ${NAME}', async () => {
            // Common case: SLACK_SIGNING_SECRET consumed by signature verification,
            // not template substitution. Bare-string declaration is fine.
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'no template references here')
            const report = await validateRevisionBundle(mkRev({ secrets: ['SLACK_SIGNING_SECRET'] }), bundles)
            expect(report.ok).toBe(true)
        })

        it('emits one error per (file, secret) even when the reference appears many times', async () => {
            const bundles = makeBundles()
            await bundles.write(
                'rev1',
                'agent.md',
                '${SLACK_BOT_TOKEN} ${SLACK_BOT_TOKEN} ${SLACK_BOT_TOKEN} ${INCIDENT_IO_TOKEN}'
            )
            const report = await validateRevisionBundle(
                mkRev({ secrets: ['SLACK_BOT_TOKEN', 'INCIDENT_IO_TOKEN'] }),
                bundles
            )
            expect(report.errors).toHaveLength(2)
            expect(report.errors.map((e) => e.code)).toEqual(['secret_no_host_binding', 'secret_no_host_binding'])
        })

        it('does NOT flag undeclared ${NAME} references (different error class)', async () => {
            // An undeclared reference is `secret_not_resolved` at runtime — a
            // different failure mode. Outside this validator's scope; the
            // bare-string-binding check is the only thing being asserted here.
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'Auth: `Bearer ${NEVER_DECLARED}`.')
            const report = await validateRevisionBundle(mkRev(), bundles)
            expect(report.ok).toBe(true)
        })
    })

    describe('mcp secret host binding', () => {
        it('flags ${NAME} in an mcp header when the secret is declared as a bare string', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            const report = await validateRevisionBundle(
                mkRev({
                    secrets: ['GITHUB_TOKEN'],
                    mcps: [
                        {
                            kind: 'agent',
                            default_tool_approval: 'allow',
                            id: 'github',
                            url: 'https://api.githubcopilot.com/mcp',
                            secrets: ['GITHUB_TOKEN'],
                            headers: { Authorization: 'Bearer ${GITHUB_TOKEN}' },
                        },
                    ],
                }),
                bundles
            )
            expect(report.ok).toBe(false)
            expect(report.errors).toEqual([
                {
                    code: 'secret_no_host_binding',
                    pointer: 'spec.mcps[0].headers.Authorization',
                    message: expect.stringContaining('GITHUB_TOKEN'),
                },
            ])
        })

        it('flags ${NAME} in an mcp url when the secret is declared as a bare string', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            const report = await validateRevisionBundle(
                mkRev({
                    secrets: ['TENANT'],
                    mcps: [
                        {
                            kind: 'agent',
                            default_tool_approval: 'allow',
                            id: 'tenant',
                            url: 'https://${TENANT}.example.com/mcp',
                            secrets: ['TENANT'],
                        },
                    ],
                }),
                bundles
            )
            expect(report.errors).toEqual([
                {
                    code: 'secret_no_host_binding',
                    pointer: 'spec.mcps[0].url',
                    message: expect.stringContaining('TENANT'),
                },
            ])
        })

        it('accepts an mcp header secret declared in object form with allowed_hosts', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            const report = await validateRevisionBundle(
                mkRev({
                    secrets: [{ name: 'GITHUB_TOKEN', allowed_hosts: ['api.githubcopilot.com'] }],
                    mcps: [
                        {
                            kind: 'agent',
                            default_tool_approval: 'allow',
                            id: 'github',
                            url: 'https://api.githubcopilot.com/mcp',
                            secrets: ['GITHUB_TOKEN'],
                            headers: { Authorization: 'Bearer ${GITHUB_TOKEN}' },
                        },
                    ],
                }),
                bundles
            )
            expect(report.ok).toBe(true)
        })

        it('does NOT flag a declared mcp secret that is never referenced as ${NAME}', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            const report = await validateRevisionBundle(
                mkRev({
                    secrets: ['GITHUB_TOKEN'],
                    mcps: [
                        {
                            kind: 'agent',
                            default_tool_approval: 'allow',
                            id: 'github',
                            url: 'https://api.githubcopilot.com/mcp',
                            secrets: ['GITHUB_TOKEN'],
                        },
                    ],
                }),
                bundles
            )
            expect(report.ok).toBe(true)
        })
    })

    describe('required client tool + non-chat trigger', () => {
        const chatAuth = { type: 'public' as const, acknowledge_public_exposure: true as const }
        const requiredClientTool = {
            kind: 'client' as const,
            id: 'connect_mcp',
            description: 'connect an mcp',
            args_schema: { type: 'object' },
            required: true,
        }
        const optionalClientTool = {
            kind: 'client' as const,
            id: 'focus',
            description: 'focus a panel',
            args_schema: { type: 'object' },
            required: false,
        }

        it('accepts a required client tool when only chat triggers are configured', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            const report = await validateRevisionBundle(
                mkRev({
                    triggers: [{ type: 'chat', config: {}, auth: { modes: [chatAuth] } }],
                    tools: [requiredClientTool],
                }),
                bundles
            )
            expect(report.ok).toBe(true)
        })

        it('rejects a required client tool when a webhook trigger is also configured', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            const report = await validateRevisionBundle(
                mkRev({
                    triggers: [
                        { type: 'chat', config: {}, auth: { modes: [chatAuth] } },
                        { type: 'webhook', config: { path: '/w' }, auth: { modes: [chatAuth] } },
                    ],
                    tools: [requiredClientTool],
                }),
                bundles
            )
            expect(report.ok).toBe(false)
            expect(report.errors).toEqual([
                {
                    code: 'required_client_tool_with_non_chat_trigger',
                    message: expect.stringContaining('connect_mcp'),
                    pointer: 'spec.tools[0].required',
                },
            ])
            expect(report.errors[0].message).toContain('webhook')
        })

        it('accepts a non-required client tool alongside non-chat triggers', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            const report = await validateRevisionBundle(
                mkRev({
                    triggers: [
                        { type: 'chat', config: {}, auth: { modes: [chatAuth] } },
                        { type: 'webhook', config: { path: '/w' }, auth: { modes: [chatAuth] } },
                    ],
                    tools: [optionalClientTool],
                }),
                bundles
            )
            expect(report.ok).toBe(true)
        })

        it('emits one error per required client tool, listing every non-chat trigger kind', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            const report = await validateRevisionBundle(
                mkRev({
                    triggers: [
                        { type: 'webhook', config: { path: '/w' }, auth: { modes: [chatAuth] } },
                        { type: 'mcp', config: {}, auth: { modes: [chatAuth] } },
                    ],
                    tools: [requiredClientTool, { ...optionalClientTool, required: true }],
                }),
                bundles
            )
            expect(report.errors).toHaveLength(2)
            for (const err of report.errors) {
                expect(err.code).toBe('required_client_tool_with_non_chat_trigger')
                expect(err.message).toMatch(/webhook.*mcp|mcp.*webhook/)
            }
        })
    })
})
