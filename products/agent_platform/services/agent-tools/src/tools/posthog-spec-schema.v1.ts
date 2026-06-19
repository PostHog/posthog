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
 * Defined as a static, no-arg, no-auth read — like the catalog tool, it
 * computes its result in-process with no API round-trip.
 */

import { z } from 'zod'

import { AgentSpecSchema, defineNativeTool, Type } from '@posthog/agent-shared'

/**
 * Orientation the bare JSON Schema doesn't make obvious. Kept short on purpose
 * — the schema is authoritative; these only point at the surrounding tools and
 * the two discriminated unions that are the usual source of validation errors.
 */
const SPEC_NOTES: readonly string[] = [
    'This is the canonical agent `spec` schema, generated from the source the API validates writes against. Pass a spec matching this shape to `agent-applications-revisions-create` / `-partial-update`.',
    'Fields that carry a JSON Schema `default` are optional on write — omit them to take the default. `model` is the only always-required field.',
    '`triggers[]` is a discriminated union on `type`. `chat`, `mcp`, and `webhook` carry an `auth` block; `slack` and `cron` do not (they authenticate via their own protocol).',
    '`tools[]` is a discriminated union on `kind` (`native` | `custom` | `client`). For valid `native` tool ids call `@posthog/agent-applications-native-tools-list` — the validator rejects unknown ids.',
    '`secrets[]` entries are either a bare string (resolvable, no network-egress authority) or `{ name, allowed_hosts }` (required to let `@posthog/http-request` send the secret to those hosts).',
    'Skill and custom-tool *content* (SKILL.md bodies, tool source/schema) is uploaded via the bundle file tools (`-skills-update` / `-tools-update`), not inline in the spec.',
]

// Pure derivation from the canonical schema — compute once at module load.
const SPEC_JSON_SCHEMA = z.toJSONSchema(AgentSpecSchema) as Record<string, unknown>

export const posthogAgentApplicationsSpecSchemaV1 = defineNativeTool({
    id: '@posthog/agent-applications-spec-schema',
    description: [
        'Return the JSON Schema for an agent `spec` — every field, type, enum, default, and the',
        'discriminated unions for `triggers[]` / `tools[]` / `secrets[]`. Call this BEFORE writing or',
        'editing a spec (create / partial-update a revision) instead of guessing the shape or copying',
        'another agent. Generated from the canonical schema the API validates against, so it never drifts.',
    ].join(' '),
    args: Type.Object({}),
    returns: Type.Object({
        spec_json_schema: Type.Record(Type.String(), Type.Unknown()),
        notes: Type.Array(Type.String()),
    }),
    cost_hint: 'cheap',
    async run() {
        return { spec_json_schema: SPEC_JSON_SCHEMA, notes: [...SPEC_NOTES] }
    },
})
