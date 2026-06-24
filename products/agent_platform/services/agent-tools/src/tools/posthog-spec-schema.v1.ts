/**
 * `@posthog/agent-applications-spec-schema` — the authoring concierge's
 * ground-truth view of the agent `spec` shape, so it stops guessing the
 * structure from (drift-prone) skill docs or reverse-engineering other
 * agents' revisions.
 *
 * Sibling of `@posthog/agent-applications-native-tools-list`: that tool
 * discovers valid tool *ids*; this one discovers the spec *shape* those ids
 * slot into. The JSON Schema is generated at call time from the canonical Zod
 * `AgentSpecSchema` (the same schema the runner parses and the Django write
 * path mirrors), so it cannot drift from what the API actually validates.
 *
 * Two things keep the result cheap. `reused: 'ref'` hoists repeated
 * subschemas (the auth-mode union, the approval policy) into `$defs` instead
 * of inlining each copy — the union alone is otherwise emitted once per
 * chat/mcp/webhook trigger. And an optional `section` returns just one slice
 * of the spec (`triggers` is ~half the whole thing), so the common
 * "edit one part" path pays for that part only. Defined as a static, no-auth
 * read: computed in-process with no API round-trip.
 */

import { z } from 'zod'

import {
    AgentSpecSchema,
    AuthConfigSchema,
    defineNativeTool,
    FrameworkPromptConfigSchema,
    McpRefSchema,
    ReasoningEffortSchema,
    ResumeConfigSchema,
    SecretRefSchema,
    SkillRefSchema,
    SpecLimitsSchema,
    ToolRefSchema,
    TriggerSchema,
    Type,
} from '@posthog/agent-shared'

// One spec slice each. `triggers`/`tools`/`secrets` are the element schemas
// (the spec field is an array of these); the rest are the field schema itself.
const SECTION_SCHEMAS = {
    triggers: TriggerSchema,
    tools: ToolRefSchema,
    mcps: McpRefSchema,
    secrets: SecretRefSchema,
    skills: SkillRefSchema,
    limits: SpecLimitsSchema,
    auth: AuthConfigSchema,
    reasoning: ReasoningEffortSchema,
    framework_prompt: FrameworkPromptConfigSchema,
    resume: ResumeConfigSchema,
} as const

type Section = keyof typeof SECTION_SCHEMAS
const SECTION_IDS = Object.keys(SECTION_SCHEMAS) as Section[]

// Pure derivations from the canonical schema — compute once at module load.
// `reused: 'ref'` dedupes shared subschemas into `$defs`.
const toJson = (schema: z.ZodType): Record<string, unknown> =>
    z.toJSONSchema(schema, { reused: 'ref' }) as Record<string, unknown>
const FULL_SCHEMA = toJson(AgentSpecSchema)
const SECTION_JSON: Record<string, Record<string, unknown>> = Object.fromEntries(
    SECTION_IDS.map((id) => [id, toJson(SECTION_SCHEMAS[id])])
)

/**
 * Orientation the bare JSON Schema doesn't make obvious. Kept short on purpose
 * — the schema is authoritative; these point at the surrounding tools and the
 * discriminated unions that are the usual source of validation errors. Scoped
 * per section so a one-slice fetch isn't padded with notes about the rest.
 */
const SHARED_NOTE =
    'Canonical agent `spec` schema, generated from the source the API validates writes against — match it exactly. Fields with a JSON Schema `default` are optional on write.'
const SECTION_NOTES: Record<string, string[]> = {
    triggers: [
        '`triggers[]` is a discriminated union on `type`. `chat`, `mcp`, and `webhook` carry an `auth` block; `slack` and `cron` authenticate via their own protocol and have none.',
        'Trigger-required secrets (`SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN` for `slack`) are NOT in `spec.secrets[]` — they come from the platform `TRIGGER_REQUIRED_SECRETS` registry and live in `encrypted_env`.',
    ],
    tools: [
        '`tools[]` is a discriminated union on `kind` (`native` | `custom` | `client`). For valid `native` ids call `@posthog/agent-applications-native-tools-list` — the validator rejects unknown ids.',
        'Skill and custom-tool *content* is uploaded via the bundle file tools (`-skills-update` / `-tools-update`), not inline in the spec.',
    ],
    secrets: [
        '`secrets[]` entries are a bare string (resolvable, no egress authority) or `{ name, allowed_hosts }` (required to let `@posthog/http-request` send the secret to those hosts).',
    ],
}
const FULL_NOTES = [
    SHARED_NOTE,
    '`model` is the only always-required field.',
    ...(SECTION_NOTES.triggers ?? []),
    ...(SECTION_NOTES.tools ?? []),
    ...(SECTION_NOTES.secrets ?? []),
]

export const posthogAgentApplicationsSpecSchemaV1 = defineNativeTool({
    id: '@posthog/agent-applications-spec-schema',
    description: [
        'Return the JSON Schema for an agent `spec` — every field, type, enum, default, and the',
        'discriminated unions for `triggers[]` / `tools[]` / `secrets[]`. Call this BEFORE writing or',
        'editing a spec instead of guessing the shape or copying another agent. Generated from the',
        'canonical schema the API validates against, so it never drifts. Pass `section` (e.g. `triggers`,',
        '`tools`, `limits`) to fetch just that slice when you are only editing one part — much cheaper',
        'than the whole spec. Omit `section` for the full schema.',
    ].join(' '),
    args: Type.Object({
        section: Type.Optional(
            Type.Union(
                SECTION_IDS.map((id) => Type.Literal(id)),
                {
                    description:
                        'Return only this part of the spec to save tokens. Omit for the whole spec. `triggers` alone is ~half the full schema.',
                }
            )
        ),
    }),
    returns: Type.Object({
        section: Type.Union([Type.String(), Type.Null()]),
        spec_json_schema: Type.Record(Type.String(), Type.Unknown()),
        notes: Type.Array(Type.String()),
    }),
    cost_hint: 'cheap',
    async run(args) {
        const section = args.section ?? null
        if (section && SECTION_JSON[section]) {
            const extra = SECTION_NOTES[section]
            return {
                section,
                spec_json_schema: SECTION_JSON[section],
                notes: extra ? [SHARED_NOTE, ...extra] : [SHARED_NOTE],
            }
        }
        return { section: null, spec_json_schema: FULL_SCHEMA, notes: [...FULL_NOTES] }
    },
})
