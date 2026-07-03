import {
    AgentSpec,
    AgentSpecSchema,
    AuthConfigSchema,
    getSecretAllowedHosts,
    MODEL_POLICY_LEVELS,
    modelPolicyToList,
    principalsMatch,
    secretHostMatches,
} from './spec'

describe('AgentSpecSchema', () => {
    it('parses a minimal spec with defaults', () => {
        const parsed = AgentSpecSchema.parse({})
        expect(parsed.models).toEqual({ mode: 'auto', level: 'medium', optimize_for: 'cost' })
        expect(parsed.triggers).toEqual([])
        expect(parsed.tools).toEqual([])
        expect(parsed.limits.max_turns).toBe(50)
    })

    it('parses a fully-populated spec', () => {
        const spec: AgentSpec = AgentSpecSchema.parse({
            models: { mode: 'auto', level: 'high' },
            triggers: [
                { type: 'slack', config: { channel_id: 'C01', mention_only: true, trusted_workspaces: '*' } },
                { type: 'webhook', config: { path: '/hook' }, auth: { modes: [{ type: 'posthog_internal' }] } },
            ],
            tools: [
                { kind: 'native', id: '@posthog/query' },
                { kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' },
            ],
            mcps: [
                {
                    kind: 'agent',
                    id: 'posthog',
                    url: 'https://app.posthog.com/api/mcp',
                    default_tool_approval: 'allow',
                },
            ],
            skills: [{ id: 'deep-research', path: 'skills/deep-research/SKILL.md' }],
            secrets: ['ACME_KEY'],
            limits: { max_turns: 10, max_tool_calls: 50, max_wall_seconds: 300 },
        })
        expect(spec.triggers).toHaveLength(2)
        expect(spec.tools).toHaveLength(2)
        expect(spec.mcps[0]).toMatchObject({ id: 'posthog', url: 'https://app.posthog.com/api/mcp' })
    })

    describe('limits.max_output_tokens', () => {
        it('defaults to undefined (runner picks a reasoning-aware default)', () => {
            const parsed = AgentSpecSchema.parse({})
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

    describe('models.manual model id format', () => {
        // ModelIdSchema enforces `<provider>/<model-id>` so a bare id doesn't
        // freeze fine and then 400 on the very first session.
        it('rejects a bare model id (no provider prefix)', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    models: { mode: 'manual', models: [{ model: 'claude-haiku-4-5' }] },
                })
            ).toThrow(/provider/)
        })

        it('rejects an uppercase provider', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    models: { mode: 'manual', models: [{ model: 'Anthropic/claude-haiku-4-5' }] },
                })
            ).toThrow(/provider/)
        })

        it('rejects a missing model id (trailing slash)', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    models: { mode: 'manual', models: [{ model: 'anthropic/' }] },
                })
            ).toThrow(/provider/)
        })

        it('accepts a canonical `<provider>/<model-id>`', () => {
            const parsed = AgentSpecSchema.parse({
                models: { mode: 'manual', models: [{ model: 'anthropic/claude-haiku-4-5' }] },
            })
            expect(parsed.models).toMatchObject({
                mode: 'manual',
                models: [{ model: 'anthropic/claude-haiku-4-5' }],
            })
        })
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
            expect(t.approval_policy.type).toBe('principal')
            expect(t.approval_policy.allow_edit).toBe(false)
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
            expect(t.approval_policy.type).toBe('principal')
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

        it('back-compat: an unmappable legacy approvers list falls back to the default principal type', () => {
            // An empty (or unrecognised) legacy `approvers` derives no `type`, so
            // it lands on the `principal` default rather than throwing.
            const spec = AgentSpecSchema.parse({
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
            const t = spec.tools[0]
            if (t.kind === 'client') {
                throw new Error('expected native tool')
            }
            expect(t.approval_policy.type).toBe('principal')
        })

        it('parses an explicit agent type', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/team-delete',
                        requires_approval: true,
                        approval_policy: { type: 'agent' },
                    },
                ],
            })
            const t = spec.tools[0]
            if (t.kind === 'client') {
                throw new Error('expected native tool')
            }
            expect(t.approval_policy.type).toBe('agent')
        })

        it.each([
            { approvers: ['session_principal'], type: 'principal' },
            { approvers: ['team_admins'], type: 'agent' },
        ])('back-compat: maps legacy approvers $approvers to type $type', ({ approvers, type }) => {
            // Specs frozen before the principal/agent split carry `approvers[]`
            // (+ `allow_agent_approver`); the preprocess derives `type` and drops
            // the legacy keys so old revisions keep validating.
            const spec = AgentSpecSchema.parse({
                model: 'x',
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/team-delete',
                        requires_approval: true,
                        approval_policy: { approvers, allow_agent_approver: false, ttl_ms: 900_000 },
                    },
                ],
            })
            const t = spec.tools[0]
            if (t.kind === 'client') {
                throw new Error('expected native tool')
            }
            expect(t.approval_policy.type).toBe(type)
            expect(t.approval_policy.ttl_ms).toBe(900_000)
            // Legacy keys are gone from the parsed shape.
            expect('approvers' in t.approval_policy).toBe(false)
            expect('allow_agent_approver' in t.approval_policy).toBe(false)
        })

        it('rejects an invalid approval type', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { type: 'session_owner' },
                        },
                    ],
                })
            ).toThrow()
        })
    })

    describe('mcps[] runtime refs', () => {
        it('parses tools[] level overrides on a connection default', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [
                    {
                        kind: 'agent',
                        id: 'linear',
                        url: 'https://mcp.linear.app/sse',
                        secrets: ['LINEAR_TOKEN'],
                        default_tool_approval: 'approve',
                        tools: [
                            { name: 'create-issue', level: 'allow' },
                            { name: 'delete-issue', level: 'deny' },
                        ],
                    },
                ],
            })
            const m = spec.mcps[0]
            expect(m.id).toBe('linear')
            expect(m.url).toBe('https://mcp.linear.app/sse')
            expect(m.secrets).toEqual(['LINEAR_TOKEN'])
            expect(m.default_tool_approval).toBe('approve')
            expect(m.tools).toEqual([
                { name: 'create-issue', level: 'allow' },
                { name: 'delete-issue', level: 'deny' },
            ])
        })

        it('parses a per-tool approval_policy override (who approves + ttl)', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://app.posthog.com/api/mcp',
                        default_tool_approval: 'allow',
                        tools: [
                            {
                                name: 'agent-applications-revisions-promote-create',
                                level: 'approve',
                                // Route this one tool's approval to the agent's owning team.
                                approval_policy: { type: 'agent', ttl_ms: 900_000 },
                            },
                        ],
                    },
                ],
            })
            const entry = spec.mcps[0].tools?.[0]
            if (entry === undefined) {
                throw new Error('expected a tool entry')
            }
            expect(entry.level).toBe('approve')
            expect(entry.approval_policy?.type).toBe('agent')
            expect(entry.approval_policy?.ttl_ms).toBe(900_000)
            // Unspecified fields fall through to the approval-policy defaults.
            expect(entry.approval_policy?.allow_edit).toBe(false)
        })

        it('defaults secrets to [] and tools to undefined when omitted on external', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                mcps: [
                    { kind: 'agent', id: 'linear', url: 'https://mcp.linear.app/sse', default_tool_approval: 'allow' },
                ],
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
                        kind: 'agent',
                        id: 'github',
                        url: 'https://api.githubcopilot.com/mcp',
                        secrets: ['GITHUB_TOKEN'],
                        default_tool_approval: 'allow',
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

        const validBase = {
            kind: 'agent',
            id: 'linear',
            url: 'https://mcp.linear.app/sse',
            default_tool_approval: 'allow',
        }
        it.each([
            { label: 'missing id', mcp: { ...validBase, id: undefined } },
            { label: 'empty id', mcp: { ...validBase, id: '' } },
            { label: 'non-URL endpoint', mcp: { ...validBase, url: 'not-a-url' } },
            { label: 'missing kind', mcp: { ...validBase, kind: undefined } },
            { label: 'bad kind', mcp: { ...validBase, kind: 'shared' } },
            { label: 'missing default_tool_approval', mcp: { ...validBase, default_tool_approval: undefined } },
            { label: 'bad default_tool_approval', mcp: { ...validBase, default_tool_approval: 'ask' } },
            { label: 'a tool entry with an empty name', mcp: { ...validBase, tools: [{ name: '', level: 'allow' }] } },
            { label: 'a tool entry with a bad level', mcp: { ...validBase, tools: [{ name: 'x', level: 'maybe' }] } },
            {
                label: 'duplicate tool names',
                mcp: {
                    ...validBase,
                    tools: [
                        { name: 'create-issue', level: 'allow' },
                        { name: 'create-issue', level: 'deny' },
                    ],
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
                        kind: 'agent',
                        id: 'linear',
                        url: 'https://mcp.linear.app/sse',
                        default_tool_approval: 'allow',
                        allowlist: ['create-issue'],
                    },
                ],
            })
            const m = spec.mcps[0]
            expect(m.tools).toBeUndefined()
            expect((m as unknown as { allowlist?: string[] }).allowlist).toBeUndefined()
        })
    })

    describe('mcps[] per-agent tool-permission model', () => {
        it('parses a connection-backed MCP (shared credential via mcp_store install id)', () => {
            const spec = AgentSpecSchema.parse({
                mcps: [
                    {
                        kind: 'agent',
                        id: 'incident',
                        url: 'https://mcp.incident.io/mcp',
                        connection: '019e7fb7-f4c0-75e2-9055-7c29a5cbb999',
                        default_tool_approval: 'approve',
                        tools: [{ name: 'create-incident', level: 'approve' }],
                    },
                ],
            })
            expect(spec.mcps[0].connection).toBe('019e7fb7-f4c0-75e2-9055-7c29a5cbb999')
        })

        it('parses a connection-wide default level, per-tool level overrides, and an entry approval_policy', () => {
            const spec = AgentSpecSchema.parse({
                mcps: [
                    {
                        kind: 'agent',
                        id: 'incident',
                        url: 'https://mcp.incident.io/mcp',
                        connection: '019e7fb7-f4c0-75e2-9055-7c29a5cbb999',
                        default_tool_approval: 'approve',
                        approval_policy: { type: 'agent', ttl_ms: 900_000 },
                        tools: [
                            { name: 'list-incidents', level: 'allow' },
                            { name: 'delete-incident', level: 'deny' },
                        ],
                    },
                ],
            })
            const m = spec.mcps[0]
            expect(m.default_tool_approval).toBe('approve')
            expect(m.approval_policy?.type).toBe('agent')
            expect(m.approval_policy?.ttl_ms).toBe(900_000)
            const allow = m.tools?.[0]
            const deny = m.tools?.[1]
            if (typeof allow === 'string' || allow === undefined || typeof deny === 'string' || deny === undefined) {
                throw new Error('expected object-form tool entries')
            }
            expect(allow.level).toBe('allow')
            expect(deny.level).toBe('deny')
        })

        it.each([
            {
                label: 'a bad connection-wide default_tool_approval',
                mcp: {
                    kind: 'agent',
                    id: 'incident',
                    url: 'https://mcp.incident.io/mcp',
                    default_tool_approval: 'ask',
                },
            },
            {
                label: 'a bad per-tool level override',
                mcp: {
                    kind: 'agent',
                    id: 'incident',
                    url: 'https://mcp.incident.io/mcp',
                    default_tool_approval: 'allow',
                    tools: [{ name: 'x', level: 'maybe' }],
                },
            },
        ])('rejects $label', ({ mcp }) => {
            expect(() => AgentSpecSchema.parse({ mcps: [mcp] })).toThrow()
        })
    })

    describe('mcps[].id (runtime tool-name prefix)', () => {
        it.each(['github__main', 'a__b', 'prod__incident'])(
            'rejects an id containing the `__` prefix separator: %s',
            (id) => {
                // The runtime exposes `<id>__<remoteName>` and the per-tool
                // approval lookup splits on the FIRST `__`. An id that itself
                // contains `__` misroutes the split, so the approval gate
                // silently never fires — even with default_tool_approval set.
                expect(() =>
                    AgentSpecSchema.parse({
                        mcps: [{ kind: 'agent', id, url: 'https://m.dev/mcp', default_tool_approval: 'approve' }],
                    })
                ).toThrow()
            }
        )

        it('accepts a normal id (single underscores and hyphens are fine)', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    mcps: [
                        {
                            kind: 'agent',
                            id: 'github-main_v2',
                            url: 'https://m.dev/mcp',
                            default_tool_approval: 'allow',
                        },
                    ],
                })
            ).not.toThrow()
        })
    })

    describe('mcps[].kind (required credential model)', () => {
        it('parses a principal-kind MCP wired to a per-asker identity provider', () => {
            const spec = AgentSpecSchema.parse({
                mcps: [
                    {
                        kind: 'principal',
                        id: 'posthog',
                        url: 'https://app.posthog.com/api/mcp',
                        default_tool_approval: 'allow',
                        auth: { provider: 'posthog' },
                    },
                ],
            })
            expect(spec.mcps[0].kind).toBe('principal')
            expect(spec.mcps[0].auth?.provider).toBe('posthog')
        })

        it.each([
            {
                label: 'a principal kind without auth.provider',
                mcp: { kind: 'principal', id: 'x', url: 'https://m.dev/mcp', default_tool_approval: 'allow' },
            },
            {
                label: 'a principal kind that also pins a connection',
                mcp: {
                    kind: 'principal',
                    id: 'x',
                    url: 'https://m.dev/mcp',
                    default_tool_approval: 'allow',
                    connection: '019e7fb7-f4c0-75e2-9055-7c29a5cbb999',
                    auth: { provider: 'posthog' },
                },
            },
            {
                label: 'an agent kind that sets auth.provider',
                mcp: {
                    kind: 'agent',
                    id: 'x',
                    url: 'https://m.dev/mcp',
                    default_tool_approval: 'allow',
                    auth: { provider: 'posthog' },
                },
            },
        ])('rejects $label', ({ mcp }) => {
            expect(() => AgentSpecSchema.parse({ mcps: [mcp] })).toThrow()
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
            expect(chat.type === 'chat' && chat.auth.modes).toEqual([
                { type: 'posthog', scopes: [], audience: 'project' },
            ])
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

    describe('secrets[] — host-binding union', () => {
        it('accepts a bare-string entry (back-compat; resolvable but unbound)', () => {
            const spec = AgentSpecSchema.parse({ model: 'x', secrets: ['ACME_KEY'] })
            expect(spec.secrets).toEqual(['ACME_KEY'])
        })

        it('accepts the object form with allowed_hosts', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                secrets: [{ name: 'SLACK_BOT_TOKEN', allowed_hosts: ['slack.com'] }],
            })
            expect(spec.secrets).toEqual([{ name: 'SLACK_BOT_TOKEN', allowed_hosts: ['slack.com'] }])
        })

        it('accepts a mix of bare-string and object entries in the same spec', () => {
            // Common during migration: existing bare-string secrets stay
            // declared (so the env-var lookup keeps working) while new ones
            // ship with host bindings. http-request only refuses egress on
            // the bare-string entries at substitution time.
            const spec = AgentSpecSchema.parse({
                model: 'x',
                secrets: ['LEGACY', { name: 'GH_PAT', allowed_hosts: ['api.github.com'] }],
            })
            expect(spec.secrets).toHaveLength(2)
        })

        it('rejects an object entry with an empty allowed_hosts array', () => {
            // Empty allowed_hosts is meaningless ("bound to nothing") and is
            // never what an author meant; the bare-string form is the way to
            // declare "no binding."
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    secrets: [{ name: 'X', allowed_hosts: [] }],
                })
            ).toThrow()
        })

        it('rejects an object entry missing the name', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    secrets: [{ allowed_hosts: ['x.example'] }],
                })
            ).toThrow()
        })
    })

    describe('getSecretAllowedHosts', () => {
        const spec: AgentSpec = AgentSpecSchema.parse({
            model: 'x',
            secrets: ['LEGACY', { name: 'GH_PAT', allowed_hosts: ['api.github.com', '*.github.com'] }],
        })

        it('returns the allowed_hosts array for an object-form entry', () => {
            expect(getSecretAllowedHosts(spec, 'GH_PAT')).toEqual(['api.github.com', '*.github.com'])
        })

        it('returns null for a bare-string entry (declared but unbound)', () => {
            // null is the load-bearing "fail-closed" signal: declared but
            // not authorised for any host — http-request refuses egress.
            expect(getSecretAllowedHosts(spec, 'LEGACY')).toBeNull()
        })

        it("returns undefined when the name isn't in spec.secrets[]", () => {
            expect(getSecretAllowedHosts(spec, 'UNKNOWN')).toBeUndefined()
        })
    })

    describe('secretHostMatches', () => {
        it.each([
            ['slack.com', 'slack.com', true],
            ['slack.com', 'SLACK.COM', true],
            ['slack.com', 'evil.com', false],
            ['slack.com', 'attacker.example', false],
            ['*.example.com', 'foo.example.com', true],
            ['*.example.com', 'a.b.example.com', true],
            ['*.example.com', 'example.com', false],
            ['*.example.com', 'evil-example.com', false],
        ])('pattern %s vs host %s -> %s', (pattern, host, expected) => {
            expect(secretHostMatches(pattern, host)).toBe(expected)
        })
    })

    describe('principalsMatch — shared_secret', () => {
        type SS = { kind: 'shared_secret'; team_id: number }
        it.each<[string, SS, SS, boolean]>([
            [
                'two secret holders for the same team match (one secret == one principal)',
                { kind: 'shared_secret', team_id: 7 },
                { kind: 'shared_secret', team_id: 7 },
                true,
            ],
            [
                'isolates across teams',
                { kind: 'shared_secret', team_id: 7 },
                { kind: 'shared_secret', team_id: 8 },
                false,
            ],
        ])('%s', (_label, stored, incoming, expected) => {
            expect(principalsMatch(stored, incoming)).toBe(expected)
        })
    })

    describe('identity_providers[] binding', () => {
        it('accepts the per-asker `principal` binding (defaulting when omitted)', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                identity_providers: [{ kind: 'posthog' }],
            })
            expect(spec.identity_providers[0]?.binding).toBe('principal')
        })

        it('rejects the unimplemented `agent` binding (the runtime seam exists, but a spec cannot select it)', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    identity_providers: [{ kind: 'posthog', binding: 'agent' }],
                })
            ).toThrow()
        })
    })
})

describe('modelPolicyToList', () => {
    it('expands an auto level to its priority list, order preserved, no reasoning by default', () => {
        const spec = AgentSpecSchema.parse({ models: { mode: 'auto', level: 'low' } })
        expect(modelPolicyToList(spec)).toEqual(
            MODEL_POLICY_LEVELS.low.map((model) => ({ model, reasoning: undefined }))
        )
    })

    it('defaults to the auto/medium list when models is omitted', () => {
        const spec = AgentSpecSchema.parse({})
        expect(modelPolicyToList(spec).map((e) => e.model)).toEqual([...MODEL_POLICY_LEVELS.medium])
    })

    it('auto: policy.reasoning applies to every resolved entry', () => {
        const spec = AgentSpecSchema.parse({ models: { mode: 'auto', level: 'high', reasoning: 'high' } })
        expect(modelPolicyToList(spec).every((e) => e.reasoning === 'high')).toBe(true)
    })

    it('auto: falls back to spec.reasoning when the policy declares none', () => {
        const spec = AgentSpecSchema.parse({ models: { mode: 'auto', level: 'medium' }, reasoning: 'low' })
        expect(modelPolicyToList(spec).every((e) => e.reasoning === 'low')).toBe(true)
    })

    it('auto: policy.reasoning wins over spec.reasoning', () => {
        const spec = AgentSpecSchema.parse({
            models: { mode: 'auto', level: 'medium', reasoning: 'xhigh' },
            reasoning: 'low',
        })
        expect(modelPolicyToList(spec).every((e) => e.reasoning === 'xhigh')).toBe(true)
    })

    it('manual: passes the explicit list through in order, per-entry reasoning preserved', () => {
        const spec = AgentSpecSchema.parse({
            models: {
                mode: 'manual',
                models: [{ model: 'anthropic/claude-opus-4-7', reasoning: 'high' }, { model: 'openai/gpt-5' }],
            },
        })
        expect(modelPolicyToList(spec)).toEqual([
            { model: 'anthropic/claude-opus-4-7', reasoning: 'high' },
            { model: 'openai/gpt-5', reasoning: undefined },
        ])
    })

    it('manual: an entry without its own reasoning inherits spec.reasoning', () => {
        const spec = AgentSpecSchema.parse({
            models: { mode: 'manual', models: [{ model: 'openai/gpt-5' }] },
            reasoning: 'medium',
        })
        expect(modelPolicyToList(spec)).toEqual([{ model: 'openai/gpt-5', reasoning: 'medium' }])
    })
})

describe('models.optimize_for', () => {
    it('defaults to cost on an auto policy', () => {
        const spec = AgentSpecSchema.parse({ models: { mode: 'auto', level: 'medium' } })
        expect(spec.models.optimize_for).toBe('cost')
    })

    it('defaults to cost on a manual policy', () => {
        const spec = AgentSpecSchema.parse({ models: { mode: 'manual', models: [{ model: 'openai/gpt-5' }] } })
        expect(spec.models.optimize_for).toBe('cost')
    })

    it('defaults to cost when models is omitted entirely', () => {
        expect(AgentSpecSchema.parse({}).models.optimize_for).toBe('cost')
    })

    it.each(['cost', 'availability'] as const)('accepts optimize_for: %s', (mode) => {
        const spec = AgentSpecSchema.parse({ models: { mode: 'auto', level: 'high', optimize_for: mode } })
        expect(spec.models.optimize_for).toBe(mode)
    })

    it('rejects an unknown optimize_for', () => {
        expect(() =>
            AgentSpecSchema.parse({ models: { mode: 'auto', level: 'high', optimize_for: 'latency' } })
        ).toThrow()
    })
})
