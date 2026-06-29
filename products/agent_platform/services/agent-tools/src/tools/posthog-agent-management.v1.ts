/**
 * Native tools for reading agent-platform state — the agent-management
 * surface the concierge needs to inspect any agent (its own
 * application, other team agents, their revisions, sessions, logs).
 *
 * All tools share the identity auth path (`_posthog-api.ts`): each declares a
 * posthog `requires.provider` and resolves the connected user's bearer via
 * `ctx.identity.resolve('posthog')` (trigger-edge seed or per-asker link).
 * An unlinked asker yields a uniform `auth_required` result (the dispatch
 * wrapper relays the link); an unavailable identity fails with
 * `posthog_credentials_unavailable` and the agent.md degradation rules kick in.
 *
 * Tool ids mirror the MCP catalog (e.g. `@posthog/agent-applications-list`
 * matches `agent-applications-list` in `services/mcp/definitions/agent_platform.yaml`)
 * so a future migration to MCP-routed dispatch keeps the same surface.
 *
 * **Reads + writes.** Authoring writes (create, partial-update, new-draft,
 * file-update, validate, freeze, promote, archive, set-env) live here too.
 * Server-side approval gating is NOT enforced — the concierge agent.md
 * (hard rules #3 + #5) requires the model to confirm before destructive
 * edits in chat, which matches what users expect from a chat-driven
 * authoring surface. Move sensitive writes back behind the runner's
 * approval pipeline if/when the dispatcher gets per-tool gating.
 */

import { defineNativeTool, type ToolContext, Type } from '@posthog/agent-shared'

import { callPosthogApi, ProjectIdArg, projectPath } from './_posthog-api'

interface AgentApplication {
    id: string
    team: number
    name: string
    slug: string
    description: string
    live_revision: string | null
    archived: boolean
    archived_at: string | null
    created_by: number | null
    created_at: string
    updated_at: string
}

interface ListResponse<T> {
    count?: number
    next?: string | null
    previous?: string | null
    results: T[]
}

const AgentApplicationSchema = Type.Object({
    id: Type.String(),
    team: Type.Number(),
    name: Type.String(),
    slug: Type.String(),
    description: Type.String(),
    live_revision: Type.Union([Type.String(), Type.Null()]),
    archived: Type.Boolean(),
    archived_at: Type.Union([Type.String(), Type.Null()]),
    created_by: Type.Union([Type.Number(), Type.Null()]),
    created_at: Type.String(),
    updated_at: Type.String(),
})

/**
 * Resolve an application by slug OR id. Lookup by slug requires a list
 * call; lookup by id is direct. Lets the concierge accept either form
 * naturally without forcing slug→id translation upstream.
 */
async function resolveApplicationId(
    ctx: ToolContext,
    ref: { slug?: string; id?: string; project_id: number }
): Promise<string> {
    if (ref.id) {
        return ref.id
    }
    if (!ref.slug) {
        throw new Error('agent_ref_required: provide either `slug` or `id`')
    }
    const list = await callPosthogApi<ListResponse<AgentApplication>>(ctx, {
        method: 'GET',
        path: projectPath(ref.project_id, '/agent_applications/'),
    })
    const hit = list.results.find((a) => a.slug === ref.slug)
    if (!hit) {
        throw new Error(`agent_not_found: no agent with slug "${ref.slug}" in this project`)
    }
    return hit.id
}

/**
 * Agent-ref props spread into each tool's `args: Type.Object({...})`.
 *
 * Deliberately not a `Type.Object` wrapped via `Type.Intersect(...)` —
 * that compiles to JSON Schema `allOf`, and Anthropic's tool-call
 * validator doesn't merge `allOf.required` arrays. The model then sees
 * `session_id` (etc.) as optional and skips it. Flat `Type.Object`
 * with spread props produces the right `required` list.
 */
const agentRefFields = {
    slug: Type.Optional(Type.String({ description: 'Application slug (e.g. "weekly-digest"). Either this or id.' })),
    id: Type.Optional(Type.String({ description: 'Application UUID. Either this or slug.' })),
}

/* ──────────────────────────────────────────────────────────────────────
 * Agent applications
 * ────────────────────────────────────────────────────────────────────── */

export const posthogAgentApplicationsListV1 = defineNativeTool({
    id: '@posthog/agent-applications-list',
    description:
        "List every agent application the connected user can see in this project. Returns id, slug, name, description, live_revision. Use when the user asks 'what agents do I have?' / 'show me my agents'.",
    args: Type.Object({
        project_id: ProjectIdArg,
        include_archived: Type.Optional(Type.Boolean({ description: 'Include archived agents (default false).' })),
    }),
    returns: Type.Object({ results: Type.Array(AgentApplicationSchema) }),
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const data = await callPosthogApi<ListResponse<AgentApplication>>(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, '/agent_applications/'),
            query: args.include_archived ? { include_archived: 'true' } : undefined,
        })
        return { results: data.results }
    },
})

export const posthogAgentApplicationsRetrieveV1 = defineNativeTool({
    id: '@posthog/agent-applications-retrieve',
    description:
        'Get the full record of one agent application by slug or id. Returns its name, description, current live_revision, archived state. Use as step 1 of inspecting any agent.',
    args: Type.Object({ project_id: ProjectIdArg, ...agentRefFields }),
    returns: AgentApplicationSchema,
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi<AgentApplication>(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/`),
        })
    },
})

/* ──────────────────────────────────────────────────────────────────────
 * Revisions
 * ────────────────────────────────────────────────────────────────────── */

const RevisionSchema = Type.Object({
    id: Type.String(),
    application: Type.String(),
    parent_revision: Type.Union([Type.String(), Type.Null()]),
    state: Type.String(),
    bundle_uri: Type.String(),
    bundle_sha256: Type.Union([Type.String(), Type.Null()]),
    spec: Type.Record(Type.String(), Type.Unknown()),
    created_by: Type.Union([Type.Number(), Type.Null()]),
    created_at: Type.String(),
    updated_at: Type.String(),
})

export const posthogAgentApplicationsRevisionsListV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-list',
    description:
        "List every revision of one agent in chronological order — draft, ready, live, archived. Use to see the agent's edit history or to find a specific revision to inspect.",
    args: Type.Object({ project_id: ProjectIdArg, ...agentRefFields }),
    returns: Type.Object({ results: Type.Array(RevisionSchema) }),
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        const data = await callPosthogApi<ListResponse<unknown>>(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/`),
        })
        return data as { results: never }
    },
})

export const posthogAgentApplicationsRevisionsRetrieveV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-retrieve',
    description:
        'Get a specific revision of an agent. Returns the full spec (model, triggers, tools, skills, limits, auth) plus the bundle_sha256 + state. Use to inspect what an agent is configured to do.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: RevisionSchema,
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/`),
        })
    },
})

export const posthogAgentApplicationsRevisionsSystemPromptV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-system-prompt',
    description:
        'Get the fully-rendered system prompt for a revision — what the model actually sees on every turn (framework preamble + agent.md + skills index). The single most informative artifact when explaining what an agent does.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: Type.Object({
        revision_id: Type.String(),
        framework_prompt_version: Type.Number(),
        system_prompt: Type.String(),
    }),
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(
                args.project_id,
                `/agent_applications/${id}/revisions/${args.revision_id}/system_prompt/`
            ),
        })
    },
})

const ManifestFileSchema = Type.Object({
    path: Type.String(),
    size: Type.Number(),
    sha256: Type.String(),
})

export const posthogAgentApplicationsRevisionsManifestV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-manifest-retrieve',
    description:
        "List every file in a revision's bundle (path + size + sha256). Use to see the bundle layout before pulling specific files. Cheap — no file content returned.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: Type.Object({
        revision_id: Type.String(),
        state: Type.String(),
        bundle_sha256: Type.Union([Type.String(), Type.Null()]),
        files: Type.Array(ManifestFileSchema),
    }),
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/manifest/`),
        })
    },
})

export const posthogAgentApplicationsRevisionsBundleRetrieveV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-bundle-retrieve',
    description:
        "Read the full typed bundle for a revision. Returns `{ agent_md, skills, tools, spec }` — the agent's system prompt, every skill body + companion files, every custom tool's source + args_schema, and the author-facing spec slice. Use this when you want to inspect or edit the whole agent. Works on any revision state.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: Type.Record(Type.String(), Type.Unknown()),
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/bundle/`),
        })
    },
})

export const posthogAgentApplicationsRevisionsSlackManifestV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-slack-manifest',
    description:
        "Generate the Slack app manifest for a revision that has a slack trigger. Returns `{ revision_id, manifest, notes, events_url, interactivity_url }`. `manifest` is a ready-to-paste Slack app manifest (JSON) for https://api.slack.com/apps?new_app=1 → 'From an app manifest' — its OAuth scopes and bot event subscriptions are DERIVED from the agent's slack trigger config (mention_only / auto_resume_threads / ack_reaction) and its Slack tools, so it subscribes to exactly the events the config needs. Hand the user the manifest plus the create-from-manifest link, and surface `notes` (e.g. invite the bot to its channels). Fails if the revision has no slack trigger.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: Type.Object({
        revision_id: Type.String(),
        manifest: Type.Record(Type.String(), Type.Unknown()),
        notes: Type.Array(Type.String()),
        events_url: Type.Union([Type.String(), Type.Null()]),
        interactivity_url: Type.Union([Type.String(), Type.Null()]),
    }),
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(
                args.project_id,
                `/agent_applications/${id}/revisions/${args.revision_id}/slack_manifest/`
            ),
        })
    },
})

/* ──────────────────────────────────────────────────────────────────────
 * Sessions
 * ────────────────────────────────────────────────────────────────────── */

const SessionSummarySchema = Type.Object({
    id: Type.String(),
    state: Type.String(),
    revision_id: Type.String(),
    external_key: Type.Union([Type.String(), Type.Null()]),
    created_at: Type.String(),
    updated_at: Type.String(),
    usage_total: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
})

export const posthogAgentApplicationsSessionsListV1 = defineNativeTool({
    id: '@posthog/agent-applications-sessions-list',
    description:
        'List recent sessions for an agent. Returns state, created_at, usage_total per session. Use to see what an agent has been doing or to find a specific session to debug.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        limit: Type.Optional(Type.Number({ description: 'Max sessions to return (default 50).' })),
        state: Type.Optional(
            Type.String({
                description: 'Filter by state: queued | running | completed | closed | cancelled | failed.',
            })
        ),
    }),
    returns: Type.Object({
        count: Type.Optional(Type.Number()),
        next: Type.Optional(Type.Union([Type.String(), Type.Null()])),
        results: Type.Array(SessionSummarySchema),
    }),
    requires: { provider: { id: 'posthog', scopes: ['agent_session:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/sessions/`),
            query: { limit: args.limit, state: args.state },
        })
    },
})

export const posthogAgentApplicationsSessionsRetrieveV1 = defineNativeTool({
    id: '@posthog/agent-applications-sessions-retrieve',
    description:
        'Get the full record of one session, including its conversation (all user/assistant/tool turns), principal, usage_total, and state. The primary tool for debugging a specific session.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        session_id: Type.String({ description: 'Session UUID.' }),
    }),
    returns: Type.Record(Type.String(), Type.Unknown()),
    requires: { provider: { id: 'posthog', scopes: ['agent_session:read'] } },
    cost_hint: 'medium',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/sessions/${args.session_id}/`),
        })
    },
})

/* ──────────────────────────────────────────────────────────────────────
 * Agent applications — writes
 *
 * The full authoring surface: create / partial-update / set-env / env-keys
 * inspection. Each tool wraps a single Django endpoint; the model composes
 * them per the editing-agents-safely / authoring-new-agents skills.
 * ────────────────────────────────────────────────────────────────────── */

export const posthogAgentApplicationsCreateV1 = defineNativeTool({
    id: '@posthog/agent-applications-create',
    description:
        'Mint a brand-new agent application. Body requires `name` + `slug`; description is optional. Returns the created application — no revisions until you create one with `@posthog/agent-applications-revisions-create`.',
    args: Type.Object({
        project_id: ProjectIdArg,
        name: Type.String({ description: 'Human-readable name (shown in lists + headers).' }),
        slug: Type.String({
            description:
                'URL-safe stable identifier (lowercase alphanumeric + hyphens). Used in every subsequent tool call.',
        }),
        description: Type.Optional(
            Type.String({
                description: 'One-paragraph description of what the agent does. Surfaces in the agents-list overview.',
            })
        ),
    }),
    returns: AgentApplicationSchema,
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, '/agent_applications/'),
            body: {
                name: args.name,
                slug: args.slug,
                description: args.description ?? '',
                archived: false,
            },
        })
    },
})

export const posthogAgentApplicationsPartialUpdateV1 = defineNativeTool({
    id: '@posthog/agent-applications-partial-update',
    description:
        'Patch the top-level fields of an agent application (`name`, `description`). To change the live revision use the freeze + promote tools; to manage env use `set-env-create`.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        name: Type.Optional(Type.String()),
        description: Type.Optional(Type.String()),
    }),
    returns: AgentApplicationSchema,
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        const body: Record<string, unknown> = {}
        if (args.name !== undefined) {
            body.name = args.name
        }
        if (args.description !== undefined) {
            body.description = args.description
        }
        return callPosthogApi(ctx, {
            method: 'PATCH',
            path: projectPath(args.project_id, `/agent_applications/${id}/`),
            body,
        })
    },
})

/* ──────────────────────────────────────────────────────────────────────
 * Revisions — writes
 * ────────────────────────────────────────────────────────────────────── */

export const posthogAgentApplicationsRevisionsCreateV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-create',
    description:
        'Open a fresh empty draft revision under an application. Use when starting from scratch (no parent revision). For branching the current live revision use `@posthog/agent-applications-revisions-new-draft-create` instead — that one clones the bundle in the same call.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        spec: Type.Record(Type.String(), Type.Unknown(), {
            description:
                'AgentSpec JSON: model, triggers, tools, skills, secrets, limits, auth. Validated server-side against the spec schema.',
        }),
        bundle_uri: Type.Optional(
            Type.String({ description: 'Optional bundle URI for the revision (default server-assigned).' })
        ),
    }),
    returns: RevisionSchema,
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        const body: Record<string, unknown> = { application_id: id, spec: args.spec }
        if (args.bundle_uri) {
            body.bundle_uri = args.bundle_uri
        }
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/`),
            body,
        })
    },
})

export const posthogAgentApplicationsRevisionsNewDraftV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-new-draft-create',
    description:
        'One-shot helper: creates a draft revision and clones every file from `source_revision_id` into the new bundle in a single round-trip. Use for the common "edit live" workflow — branch from current live, mutate files, freeze, promote.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        source_revision_id: Type.String({ description: 'Revision UUID to clone bundle + spec from.' }),
    }),
    returns: Type.Object({ revision: RevisionSchema, source_revision_id: Type.String() }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/new_draft/`),
            body: { application_id: id, source_revision_id: args.source_revision_id },
        })
    },
})

export const posthogAgentApplicationsRevisionsPartialUpdateV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-partial-update',
    description:
        'Replace `spec` on a draft revision. Only `state=draft` accepts spec edits — promoting flips to `ready` which freezes the spec. Validation against AgentSpec runs server-side; an invalid spec surfaces at the next session start, not here.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID (must be `state=draft`).' }),
        spec: Type.Record(Type.String(), Type.Unknown(), {
            description:
                'Full AgentSpec to replace the current spec with. Partial-spec patching is not supported — pass the complete shape.',
        }),
    }),
    returns: RevisionSchema,
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'PATCH',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/`),
            body: { spec: args.spec },
        })
    },
})

// ── typed bundle authoring API ──────────────────────────────────────────
// Authors no
// longer write file paths — they write typed resources (agent_md, spec,
// skills, tools). The single-file file-update / file-retrieve tools were
// removed; the replacements are below.

export const posthogAgentApplicationsRevisionsAgentMdUpdateV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-agent-md-update',
    description: "Replace the agent's system prompt (`agent.md`). Draft-only.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID (must be `state=draft`).' }),
        content: Type.String({ description: 'Full system prompt body.' }),
    }),
    returns: Type.Object({ ok: Type.Boolean(), bytes: Type.Number() }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'PUT',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/agent_md/`),
            body: { content: args.content },
        })
    },
})

// Skills are authored in the llma-skill store (the canonical source) and an
// agent *references* them — there is no inline skill authoring. An agent's
// skills are `skill_refs` resolved into the bundle at freeze. Find/author store
// skills with `@posthog/llm-skills-search` / `@posthog/llm-skills-create`, then
// attach them with `@posthog/agent-applications-revisions-skill-refs-set`.
export const posthogAgentApplicationsRevisionsSkillRefsSetV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-skill-refs-set',
    description:
        "Set the complete list of store-skill references on a draft revision (full replace). Each ref is `{ from_template, alias, version? }`: `from_template` is the skill NAME in the llma-skill store, `alias` is the folder it's materialized under in the bundle (`skills/<alias>/`), `version` optionally pins a published version (omit to pin the latest at freeze). At freeze the referenced skills are resolved and baked into the bundle. Find skills with `@posthog/llm-skills-search`; author a new one with `@posthog/llm-skills-create`. Draft-only.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID (must be `state=draft`).' }),
        skill_refs: Type.Array(
            Type.Object({
                from_template: Type.String({ description: 'Skill name in the llma-skill store to pin.' }),
                alias: Type.String({
                    description:
                        'Bundle folder the skill is materialized under (lowercase letters, digits, hyphens, underscores); unique within the revision.',
                }),
                version: Type.Optional(
                    Type.Integer({ description: 'Pinned published version. Omit to pin the latest at freeze.' })
                ),
            }),
            { description: 'The complete set of references; replaces any existing ones.' }
        ),
    }),
    returns: Type.Record(Type.String(), Type.Unknown()),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'PUT',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/skill_refs/`),
            body: { skill_refs: args.skill_refs },
        })
    },
})

export const posthogLlmSkillsSearchV1 = defineNativeTool({
    id: '@posthog/llm-skills-search',
    description:
        'Search the llma-skill store for reusable skills in this project. Returns name, description, version, category per match. Use to find a skill to attach to an agent (via `@posthog/agent-applications-revisions-skill-refs-set`) before authoring a new one.',
    args: Type.Object({
        project_id: ProjectIdArg,
        search: Type.Optional(
            Type.String({ description: 'Free-text search over name + description. Omit to list all skills.' })
        ),
    }),
    returns: Type.Object({ results: Type.Array(Type.Record(Type.String(), Type.Unknown())) }),
    requires: { provider: { id: 'posthog', scopes: ['llm_skill:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const data = await callPosthogApi<ListResponse<Record<string, unknown>>>(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, '/llm_skills/'),
            query: args.search ? { search: args.search } : undefined,
        })
        return { results: data.results }
    },
})

export const posthogLlmSkillsCreateV1 = defineNativeTool({
    id: '@posthog/llm-skills-create',
    description:
        'Author a new skill in the llma-skill store — the canonical place skills live. Provide `name` (stable id across versions), `description` (when-to-load hint shown in the agent skill index), `body` (SKILL.md markdown), and optional `files` (companion docs). Returns the created skill. Attach it to an agent with `@posthog/agent-applications-revisions-skill-refs-set`.',
    args: Type.Object({
        project_id: ProjectIdArg,
        name: Type.String({ description: 'Skill name — stable identifier across versions.' }),
        description: Type.String({ description: 'When-to-load hint shown in the agent skill index.' }),
        body: Type.String({ description: 'SKILL.md markdown body.' }),
        files: Type.Optional(
            Type.Array(Type.Object({ path: Type.String(), content: Type.String() }), {
                description: 'Optional companion files (path relative to the skill folder).',
            })
        ),
    }),
    returns: Type.Record(Type.String(), Type.Unknown()),
    requires: { provider: { id: 'posthog', scopes: ['llm_skill:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, '/llm_skills/'),
            body: { name: args.name, description: args.description, body: args.body, files: args.files ?? [] },
        })
    },
})

export const posthogAgentApplicationsRevisionsToolsUpdateV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-tools-update',
    description:
        "Upsert one custom tool in a draft revision. The janitor runs an AST shape check + esbuild compile synchronously and returns 422 with structured diagnostics on failure — no half-written tool ever lands. Required source shape: `export default { actions: { default: async (args, ctx) => { ... } } }`. Do NOT include `compiled.js` — it's generated.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID (must be `state=draft`).' }),
        tool_id: Type.String({ description: 'Tool slug (lowercase alphanumeric, hyphens, underscores).' }),
        description: Type.String({ description: 'Description the model sees when picking tools.' }),
        args_schema: Type.Record(Type.String(), Type.Unknown(), {
            description: "JSON Schema for the tool's args. Free-form object; the runner doesn't introspect it.",
        }),
        source: Type.String({ description: 'TypeScript source.' }),
    }),
    returns: Type.Object({ ok: Type.Boolean(), tool_id: Type.String() }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'PUT',
            path: projectPath(
                args.project_id,
                `/agent_applications/${id}/revisions/${args.revision_id}/tools/${args.tool_id}/`
            ),
            body: { description: args.description, args_schema: args.args_schema, source: args.source },
        })
    },
})

export const posthogAgentApplicationsRevisionsToolsDestroyV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-tools-destroy',
    description: 'Delete one custom tool (source.ts + compiled.js + schema.json). Draft-only.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID (must be `state=draft`).' }),
        tool_id: Type.String({ description: 'Tool slug.' }),
    }),
    returns: Type.Object({ ok: Type.Boolean(), tool_id: Type.String() }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'DELETE',
            path: projectPath(
                args.project_id,
                `/agent_applications/${id}/revisions/${args.revision_id}/tools/${args.tool_id}/`
            ),
        })
    },
})

export const posthogAgentApplicationsRevisionsValidateV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-validate-create',
    description:
        "Pre-flight check on any revision state. Surfaces missing entrypoints, unknown tool ids, custom tools missing compiled.js / schema.json, skill paths that don't exist, declared secrets that aren't set. Always run before freeze. Returns `{ ok, errors, resolved_natives }`.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: Type.Object({
        ok: Type.Boolean(),
        revision_id: Type.String(),
        revision_state: Type.String(),
        errors: Type.Array(Type.Record(Type.String(), Type.Unknown())),
        resolved_natives: Type.Optional(Type.Array(Type.String())),
    }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/validate/`),
        })
    },
})

export const posthogAgentApplicationsRevisionsFreezeV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-freeze-create',
    description:
        'Walk the bundle, compute a manifest sha256, stamp it on the row, flip state `draft → ready`. After freeze the bundle is immutable. Idempotent — freezing a `ready` revision returns the existing sha256.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID (must be `state=draft` or `ready`).' }),
    }),
    returns: Type.Object({
        ok: Type.Boolean(),
        state: Type.String(),
        bundle_sha256: Type.String(),
        revision: RevisionSchema,
    }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/freeze/`),
        })
    },
})

export const posthogAgentApplicationsRevisionsPromoteV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-promote-create',
    description:
        "Flip a `ready` revision to `live` and set the parent application's `live_revision`. The previously-live revision is archived automatically. Requires `state=ready` and `bundle_sha256` set (call `freeze` first). Idempotent. SERVER-SIDE GATE: refuses with a clear error if trigger-required secrets (e.g. `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN` for slack triggers) are missing from the agent's `encrypted_env` — see `skills/setting-up-slack-app`. PER AGENT.MD HARD RULE #3: confirm with the user explicitly before calling.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID (must be `state=ready`).' }),
    }),
    returns: Type.Object({ ok: Type.Boolean(), state: Type.String() }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/promote/`),
        })
    },
})

export const posthogAgentApplicationsRevisionsArchiveV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-archive-create',
    description:
        "Archive any revision. Clears the parent application's `live_revision` if the archived revision was live. DESTRUCTIVE per agent.md hard rule #5 — confirm with the user before calling.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID to archive.' }),
    }),
    returns: Type.Object({ ok: Type.Boolean(), state: Type.String() }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, `/agent_applications/${id}/revisions/${args.revision_id}/archive/`),
        })
    },
})

/* ──────────────────────────────────────────────────────────────────────
 * Encrypted env — list / get / clear individual keys
 *
 * Writes (set / rotate) deliberately route through the `set_secret`
 * client tool in the console UI — not through a native tool.
 * That keeps secret values out of the session tool-call history. See
 * `skills/secrets-and-integrations`.
 *
 * `set-env-create` (raw API for CI scripts) is wired anyway so the
 * concierge can recover from the rare case where the punch-out form is
 * broken or unavailable. The model is told to prefer the client tool.
 * ────────────────────────────────────────────────────────────────────── */

const EnvKeyRowSchema = Type.Object({
    key: Type.String(),
    is_set: Type.Boolean(),
})

export const posthogAgentApplicationsEnvKeysListV1 = defineNativeTool({
    id: '@posthog/agent-applications-env-keys-list',
    description:
        'List every encrypted_env key set on an agent, with `is_set` per row. Does NOT return the values — those are encrypted at rest and never read back through this surface. Use to audit which secrets the agent has configured before freeze + promote.',
    args: Type.Object({ project_id: ProjectIdArg, ...agentRefFields }),
    returns: Type.Object({ keys: Type.Array(EnvKeyRowSchema) }),
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/env_keys/`),
        })
    },
})

export const posthogAgentApplicationsEnvKeysGetV1 = defineNativeTool({
    id: '@posthog/agent-applications-env-keys-get',
    description:
        'Probe whether a single encrypted_env key is set on an agent. Returns `{ key, is_set }`. Never returns the value. Use as the precheck before triggering the `set_secret` punch-out flow.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        key: Type.String({ description: 'Env key to probe, e.g. `SLACK_BOT_TOKEN`.' }),
    }),
    returns: EnvKeyRowSchema,
    requires: { provider: { id: 'posthog', scopes: ['agents:read'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/env_keys/${args.key}/`),
        })
    },
})

export const posthogAgentApplicationsSetEnvV1 = defineNativeTool({
    id: '@posthog/agent-applications-set-env-create',
    description:
        'Replace the entire encrypted_env block. WARNING: puts secret values in the session tool-call history. Per `skills/secrets-and-integrations`, prefer the `set_secret` client tool (UI punch-out, never logs values). Use this raw API only when the user explicitly opts in (broken punch-out, CI script, etc.) — confirm before calling and warn about the trace.',
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        env: Type.Record(Type.String(), Type.String(), {
            description:
                'Key/value map of env entries. REPLACES the existing block — keys not in this map are deleted.',
        }),
    }),
    returns: Type.Object({ ok: Type.Boolean() }),
    requires: { provider: { id: 'posthog', scopes: ['agents:write'] } },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'POST',
            path: projectPath(args.project_id, `/agent_applications/${id}/set_env/`),
            body: { env: args.env },
        })
    },
})

export const posthogAgentApplicationsSessionLogsV1 = defineNativeTool({
    id: '@posthog/agent-applications-session-logs',
    description:
        "Get the structured event log for a session — session_started, turn_started, tool_call, tool_result, completed/failed events. Use after sessions-retrieve when you need turn-by-turn timing or error events the conversation doesn't carry.",
    args: Type.Object({
        project_id: ProjectIdArg,
        ...agentRefFields,
        session_id: Type.String({ description: 'Session UUID.' }),
    }),
    returns: Type.Object({
        events: Type.Array(Type.Record(Type.String(), Type.Unknown())),
    }),
    requires: { provider: { id: 'posthog', scopes: ['agent_session:read'] } },
    cost_hint: 'medium',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(args.project_id, `/agent_applications/${id}/sessions/${args.session_id}/logs/`),
        })
    },
})
