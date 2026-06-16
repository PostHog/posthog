import { AgentSpec, AgentSpecSchema, AuthConfigSchema, principalsMatch } from './spec'

describe('AgentSpecSchema', () => {
    it('parses a minimal spec with defaults', () => {
        const parsed = AgentSpecSchema.parse({ model: 'claude-opus-4-7' })
        expect(parsed.model).toBe('claude-opus-4-7')
        expect(parsed.triggers).toEqual([])
        expect(parsed.tools).toEqual([])
        expect(parsed.entrypoint).toBe('agent.md')
        expect(parsed.limits.max_turns).toBe(50)
    })

    it('parses a fully-populated spec', () => {
        const spec: AgentSpec = AgentSpecSchema.parse({
            model: 'claude-opus-4-7',
            triggers: [
                { type: 'slack', config: { channel_id: 'C01', mention_only: true, trusted_workspaces: '*' } },
                { type: 'webhook', config: { path: '/hook' }, auth: { modes: [{ type: 'posthog_internal' }] } },
            ],
            tools: [
                { kind: 'native', id: '@posthog/query' },
                { kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' },
            ],
            mcps: [{ id: 'posthog', url: 'https://app.posthog.com/api/mcp' }],
            skills: [{ id: 'deep-research', path: 'skills/deep-research/SKILL.md' }],
            integrations: ['slack:T01'],
            secrets: ['ACME_KEY'],
            limits: { max_turns: 10, max_tool_calls: 50, max_wall_seconds: 300 },
            entrypoint: 'agent.md',
        })
        expect(spec.triggers).toHaveLength(2)
        expect(spec.tools).toHaveLength(2)
        expect(spec.mcps[0]).toMatchObject({ id: 'posthog', url: 'https://app.posthog.com/api/mcp' })
    })

    describe('limits.max_output_tokens', () => {
        it('defaults to undefined (runner picks a reasoning-aware default)', () => {
            const parsed = AgentSpecSchema.parse({ model: 'x' })
            expect(parsed.limits.max_output_tokens).toBeUndefined()
        })

        it('accepts an integer value', () => {
            const parsed = AgentSpecSchema.parse({ model: 'x', limits: { max_output_tokens: 16_384 } })
            expect(parsed.limits.max_output_tokens).toBe(16_384)
        })

        it('rejects zero and negative values', () => {
            expect(() => AgentSpecSchema.parse({ model: 'x', limits: { max_output_tokens: 0 } })).toThrow()
            expect(() => AgentSpecSchema.parse({ model: 'x', limits: { max_output_tokens: -1 } })).toThrow()
        })

        it('rejects values above the typo-guard upper bound', () => {
            expect(() => AgentSpecSchema.parse({ model: 'x', limits: { max_output_tokens: 200_001 } })).toThrow()
        })
    })

    it('rejects unknown trigger type', () => {
        expect(() =>
            AgentSpecSchema.parse({ model: 'x', triggers: [{ type: 'carrier-pigeon', config: {} }] })
        ).toThrow()
    })

    it('rejects unknown tool kind', () => {
        expect(() => AgentSpecSchema.parse({ model: 'x', tools: [{ kind: 'rogue', id: 'x' }] })).toThrow()
    })

    describe('cron trigger config', () => {
        const minimal = {
            name: 'weekly-digest',
            schedule: '0 9 * * MON',
            prompt: 'Produce the digest.',
        }

        it('parses a minimal cron trigger with all defaults', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                triggers: [{ type: 'cron', config: minimal }],
            })
            const t = spec.triggers[0]
            if (t.type !== 'cron') {
                throw new Error('expected cron trigger')
            }
            expect(t.config.name).toBe('weekly-digest')
            expect(t.config.timezone).toBe('UTC')
            expect(t.config.catch_up).toBe('most_recent')
            expect(t.config.max_catch_up_age_seconds).toBe(3600)
            expect(t.config.external_key).toBeUndefined()
        })

        it('parses a fully-populated cron trigger', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                triggers: [
                    {
                        type: 'cron',
                        config: {
                            ...minimal,
                            timezone: 'US/Pacific',
                            external_key: 'digest-{fired_at:week}',
                            catch_up: 'skip',
                            max_catch_up_age_seconds: 7200,
                        },
                    },
                ],
            })
            const t = spec.triggers[0]
            if (t.type !== 'cron') {
                throw new Error('expected cron trigger')
            }
            expect(t.config.timezone).toBe('US/Pacific')
            expect(t.config.external_key).toBe('digest-{fired_at:week}')
            expect(t.config.catch_up).toBe('skip')
            expect(t.config.max_catch_up_age_seconds).toBe(7200)
        })

        it('rejects a name with disallowed characters', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    triggers: [{ type: 'cron', config: { ...minimal, name: 'Weekly_Digest' } }],
                })
            ).toThrow()
        })

        it('rejects a name with a leading hyphen', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    triggers: [{ type: 'cron', config: { ...minimal, name: '-digest' } }],
                })
            ).toThrow()
        })

        it('rejects an empty schedule', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    triggers: [{ type: 'cron', config: { ...minimal, schedule: '' } }],
                })
            ).toThrow()
        })

        it('rejects an empty prompt', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    triggers: [{ type: 'cron', config: { ...minimal, prompt: '' } }],
                })
            ).toThrow()
        })

        it('rejects a prompt longer than 4096 chars', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    triggers: [{ type: 'cron', config: { ...minimal, prompt: 'x'.repeat(4097) } }],
                })
            ).toThrow()
        })

        it('rejects an unknown catch_up mode', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    triggers: [{ type: 'cron', config: { ...minimal, catch_up: 'fire-twice' } }],
                })
            ).toThrow()
        })

        it('rejects max_catch_up_age_seconds above the 7-day cap', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    triggers: [{ type: 'cron', config: { ...minimal, max_catch_up_age_seconds: 7 * 86400 + 1 } }],
                })
            ).toThrow()
        })

        it('rejects max_catch_up_age_seconds below 1', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    triggers: [{ type: 'cron', config: { ...minimal, max_catch_up_age_seconds: 0 } }],
                })
            ).toThrow()
        })
    })

    describe('framework_prompt config', () => {
        it('defaults to undefined when not present', () => {
            const spec = AgentSpecSchema.parse({ model: 'x' })
            expect(spec.framework_prompt).toBeUndefined()
        })

        it('parses an empty config with default omit list', () => {
            const spec = AgentSpecSchema.parse({ model: 'x', framework_prompt: {} })
            expect(spec.framework_prompt?.omit).toEqual([])
        })

        it('parses a populated omit list', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                framework_prompt: { omit: ['meta_tool_guidance', 'reasoning_hint'] },
            })
            expect(spec.framework_prompt?.omit).toEqual(['meta_tool_guidance', 'reasoning_hint'])
        })

        it('rejects unknown omit values', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    framework_prompt: { omit: ['unknown_section'] },
                })
            ).toThrow()
        })

        it('parses a version_pin', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                framework_prompt: { version_pin: 1 },
            })
            expect(spec.framework_prompt?.version_pin).toBe(1)
        })

        it('rejects negative version_pin', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    framework_prompt: { version_pin: 0 },
                })
            ).toThrow()
        })
    })

    describe('approval-gated tools', () => {
        it('defaults tools to requires_approval: false with admin-only policy', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                tools: [{ kind: 'native', id: '@posthog/query' }],
            })
            const t = spec.tools[0]
            // Narrow off the new `kind: "client"` variant; this test
            // covers native/custom approval defaults.
            if (t.kind === 'client') {
                throw new Error('expected native tool')
            }
            expect(t.requires_approval).toBe(false)
            expect(t.approval_policy.approvers).toEqual(['team_admins'])
            expect(t.approval_policy.allow_edit).toBe(false)
            expect(t.approval_policy.allow_agent_approver).toBe(false)
            expect(t.approval_policy.ttl_ms).toBe(24 * 60 * 60 * 1000)
        })

        it('parses requires_approval: true with overridden policy fields', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/team-delete',
                        requires_approval: true,
                        approval_policy: { allow_edit: true, ttl_ms: 60 * 60 * 1000 },
                    },
                ],
            })
            const t = spec.tools[0]
            if (t.kind === 'client') {
                throw new Error('expected native tool')
            }
            expect(t.requires_approval).toBe(true)
            expect(t.approval_policy.allow_edit).toBe(true)
            expect(t.approval_policy.ttl_ms).toBe(60 * 60 * 1000)
            // unspecified fields still defaulted
            expect(t.approval_policy.approvers).toEqual(['team_admins'])
            expect(t.approval_policy.allow_agent_approver).toBe(false)
        })

        it('rejects ttl_ms below 1 minute', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { ttl_ms: 30_000 },
                        },
                    ],
                })
            ).toThrow()
        })

        it('rejects ttl_ms above 7 days', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { ttl_ms: 30 * 24 * 60 * 60 * 1000 },
                        },
                    ],
                })
            ).toThrow()
        })

        it('rejects empty approvers list', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { approvers: [] },
                        },
                    ],
                })
            ).toThrow()
        })

        it('parses session_principal as an approver scope', () => {
            // PR 7 widened the v0 enum from `['team_admins']` to add
            // `['session_principal']` so the concierge can route gated
            // calls back to the session owner via the per-asker fast path.
            const spec = AgentSpecSchema.parse({
                model: 'x',
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/team-delete',
                        requires_approval: true,
                        approval_policy: { approvers: ['session_principal'] },
                    },
                ],
            })
            const t = spec.tools[0]
            if (t.kind === 'client') {
                throw new Error('expected native tool')
            }
            expect(t.approval_policy.approvers).toEqual(['session_principal'])
        })

        it('rejects approver scopes not yet supported in v0', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { approvers: ['session_owner'] },
                        },
                    ],
                })
            ).toThrow()
        })
    })

    describe('mcps[] runtime refs', () => {
        it('parses an external MCP with bare-string tools[] (passthrough, no gating)', () => {
            // Bare strings in tools[] are the post-PR-7 equivalent of the
            // old allowlist[]: gates inclusion, no approval policy.
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [
                    {
                        id: 'linear',
                        url: 'https://mcp.linear.app/sse',
                        auth: { integration: 'linear:T01' },
                        secrets: ['LINEAR_TOKEN'],
                        tools: ['create-issue', 'list-issues'],
                    },
                ],
            })
            const m = spec.mcps[0]
            expect(m.id).toBe('linear')
            expect(m.url).toBe('https://mcp.linear.app/sse')
            expect(m.auth?.integration).toBe('linear:T01')
            expect(m.secrets).toEqual(['LINEAR_TOKEN'])
            expect(m.tools).toEqual(['create-issue', 'list-issues'])
        })

        it('parses object-form tools[] entries with approval gating', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [
                    {
                        id: 'posthog',
                        url: 'https://app.posthog.com/api/mcp',
                        tools: [
                            'agent-applications-list',
                            {
                                name: 'agent-applications-revisions-promote-create',
                                requires_approval: true,
                                approval_policy: { approvers: ['session_principal'], ttl_ms: 900_000 },
                            },
                        ],
                    },
                ],
            })
            const m = spec.mcps[0]
            expect(m.tools?.[0]).toBe('agent-applications-list')
            const gated = m.tools?.[1]
            if (typeof gated === 'string' || gated === undefined) {
                throw new Error('expected object-form tool entry')
            }
            expect(gated.name).toBe('agent-applications-revisions-promote-create')
            expect(gated.requires_approval).toBe(true)
            expect(gated.approval_policy.approvers).toEqual(['session_principal'])
            expect(gated.approval_policy.ttl_ms).toBe(900_000)
            // Unspecified fields fall through to the approval-policy defaults.
            expect(gated.approval_policy.allow_edit).toBe(false)
        })

        it('object-form tools[] entries default requires_approval to false', () => {
            // Object form without explicit gating means "include this tool
            // with no approval gate" — same effective behaviour as the
            // bare-string form, just expressed as an object. Useful when an
            // author wants the object slot reserved for a future config knob
            // (e.g. description override) without flipping the gate on.
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [
                    {
                        id: 'linear',
                        url: 'https://mcp.linear.app/sse',
                        tools: [{ name: 'create-issue' }],
                    },
                ],
            })
            const m = spec.mcps[0]
            const entry = m.tools?.[0]
            if (typeof entry === 'string' || entry === undefined) {
                throw new Error('expected object-form tool entry')
            }
            expect(entry.requires_approval).toBe(false)
        })

        it('defaults secrets to [] and tools to undefined when omitted on external', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [{ id: 'linear', url: 'https://mcp.linear.app/sse' }],
            })
            const m = spec.mcps[0]
            expect(m.secrets).toEqual([])
            expect(m.tools).toBeUndefined()
            expect(m.headers).toBeUndefined()
        })

        it('parses author-supplied headers with secret references for BYO bearer tokens', () => {
            // Unblocks GitHub MCP / Linear MCP / any HTTP-API'd MCP with a
            // bearer-token auth model. Same substitution semantics as
            // @posthog/http-request — the runner walks headers + substitutes
            // ${NAME} from `secrets[]` before opening the client.
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [
                    {
                        id: 'github',
                        url: 'https://api.githubcopilot.com/mcp',
                        secrets: ['GITHUB_TOKEN'],
                        headers: {
                            Authorization: 'Bearer ${GITHUB_TOKEN}',
                            'X-GitHub-Api-Version': '2022-11-28',
                        },
                    },
                ],
            })
            const m = spec.mcps[0]
            expect(m.headers).toEqual({
                Authorization: 'Bearer ${GITHUB_TOKEN}',
                'X-GitHub-Api-Version': '2022-11-28',
            })
        })

        it.each([
            { label: 'missing id', mcp: { url: 'https://mcp.linear.app/sse' } },
            { label: 'empty id', mcp: { id: '', url: 'https://mcp.linear.app/sse' } },
            { label: 'non-URL endpoint', mcp: { id: 'linear', url: 'not-a-url' } },
            {
                label: 'tools entry with empty name string',
                mcp: { id: 'linear', url: 'https://mcp.linear.app/sse', tools: [''] },
            },
            {
                label: 'tools object with empty name',
                mcp: {
                    id: 'linear',
                    url: 'https://mcp.linear.app/sse',
                    tools: [{ name: '' }],
                },
            },
            {
                label: 'duplicate bare-string entries',
                mcp: {
                    id: 'linear',
                    url: 'https://mcp.linear.app/sse',
                    tools: ['create-issue', 'create-issue'],
                },
            },
            {
                label: 'a bare-string entry duplicating an object entry name',
                mcp: {
                    id: 'linear',
                    url: 'https://mcp.linear.app/sse',
                    tools: ['create-issue', { name: 'create-issue', requires_approval: true }],
                },
            },
        ])('rejects an external entry with $label', ({ mcp }) => {
            expect(() => AgentSpecSchema.parse({ model: 'x', mcps: [mcp] })).toThrow()
        })

        it('silently drops a legacy `allowlist[]` field (zod default + PR 7 hard-break)', () => {
            // Documents the post-PR-7 break: zod tolerates unknown fields by
            // default, so `allowlist` parses through as no-op — the runtime
            // behaviour changes hard (the filter is gone). Authors rebasing
            // from pre-PR-7 see every tool surface to the model instead of
            // their old narrowed set. This test pins the no-op so a future
            // `.strict()` add (which would reject) is a conscious choice.
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [
                    {
                        id: 'linear',
                        url: 'https://mcp.linear.app/sse',
                        allowlist: ['create-issue'],
                    },
                ],
            })
            const m = spec.mcps[0]
            expect(m.tools).toBeUndefined()
            expect((m as unknown as { allowlist?: string[] }).allowlist).toBeUndefined()
        })
    })

    describe('resume config (per-agent TTL on completed sessions)', () => {
        it('defaults to undefined when not present (preserves today behaviour)', () => {
            const spec = AgentSpecSchema.parse({ model: 'x' })
            expect(spec.resume).toBeUndefined()
        })

        it('applies sensible defaults when an empty resume section is present', () => {
            const spec = AgentSpecSchema.parse({ model: 'x', resume: {} })
            expect(spec.resume?.enabled).toBe(false)
            expect(spec.resume?.max_completed_age_ms).toBe(7 * 24 * 60 * 60_000)
        })

        it('parses an opt-in week-long TTL config', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                resume: { enabled: true, max_completed_age_ms: 14 * 24 * 60 * 60_000 },
            })
            expect(spec.resume?.enabled).toBe(true)
            expect(spec.resume?.max_completed_age_ms).toBe(14 * 24 * 60 * 60_000)
        })

        it('rejects a non-positive max_completed_age_ms', () => {
            expect(() => AgentSpecSchema.parse({ model: 'x', resume: { max_completed_age_ms: 0 } })).toThrow()
        })
    })

    describe('auth (per-trigger)', () => {
        it('AuthConfig defaults to closed posthog_internal — public is opt-in', () => {
            expect(AuthConfigSchema.parse({})).toEqual({ modes: [{ type: 'posthog_internal' }] })
        })

        it('declarative triggers require an auth block', () => {
            // webhook/chat/mcp must declare who can call them — no implicit default.
            expect(() =>
                AgentSpecSchema.parse({ model: 'x', triggers: [{ type: 'webhook', config: { path: '/h' } }] })
            ).toThrow()
        })

        it('per-trigger auth lands on the trigger', () => {
            const parsed = AgentSpecSchema.parse({
                model: 'x',
                triggers: [{ type: 'chat', config: {}, auth: { modes: [{ type: 'posthog' }] } }],
            })
            const chat = parsed.triggers[0]
            expect(chat.type === 'chat' && chat.auth.modes).toEqual([{ type: 'posthog', scopes: [] }])
        })

        it('rejects bare public — acknowledge_public_exposure: true is required', () => {
            expect(() => AuthConfigSchema.parse({ modes: [{ type: 'public' }] })).toThrow(/acknowledge_public_exposure/)
        })

        it('rejects public with acknowledge_public_exposure: false', () => {
            expect(() =>
                AuthConfigSchema.parse({ modes: [{ type: 'public', acknowledge_public_exposure: false }] })
            ).toThrow()
        })

        it('accepts public when the ack field is true', () => {
            expect(
                AuthConfigSchema.parse({ modes: [{ type: 'public', acknowledge_public_exposure: true }] }).modes
            ).toEqual([{ type: 'public', acknowledge_public_exposure: true }])
        })

        it('shared_secret requires a secret_ref', () => {
            expect(() => AuthConfigSchema.parse({ modes: [{ type: 'shared_secret', header: 'X' }] })).toThrow()
            expect(
                AuthConfigSchema.parse({ modes: [{ type: 'shared_secret', header: 'X', secret_ref: 'K' }] }).modes
            ).toHaveLength(1)
        })

        it('posthog / posthog_internal / jwt parse', () => {
            const parsed = AuthConfigSchema.parse({
                modes: [{ type: 'posthog' }, { type: 'posthog_internal' }, { type: 'jwt', issuer_secret_ref: 'S' }],
            })
            expect(parsed.modes).toHaveLength(3)
        })
    })

    describe('principalsMatch — shared_secret per-caller binding', () => {
        type SS = { kind: 'shared_secret'; team_id: number; caller_id?: string }
        it.each<[string, SS, SS, boolean]>([
            [
                'two secret holders with no caller_id match (single-principal default)',
                { kind: 'shared_secret', team_id: 7 },
                { kind: 'shared_secret', team_id: 7 },
                true,
            ],
            [
                'a session bound to a caller_id rejects a different caller',
                { kind: 'shared_secret', team_id: 7, caller_id: 'alice' },
                { kind: 'shared_secret', team_id: 7, caller_id: 'bob' },
                false,
            ],
            [
                'a caller can resume their own caller_id-bound session',
                { kind: 'shared_secret', team_id: 7, caller_id: 'alice' },
                { kind: 'shared_secret', team_id: 7, caller_id: 'alice' },
                true,
            ],
            [
                'an unbound stored session does not match a caller_id-bearing request',
                { kind: 'shared_secret', team_id: 7 },
                { kind: 'shared_secret', team_id: 7, caller_id: 'alice' },
                false,
            ],
            [
                'still isolates across teams',
                { kind: 'shared_secret', team_id: 7 },
                { kind: 'shared_secret', team_id: 8 },
                false,
            ],
        ])('%s', (_label, stored, incoming, expected) => {
            expect(principalsMatch(stored, incoming)).toBe(expected)
        })
    })
})
