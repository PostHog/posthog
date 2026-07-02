/**
 * The agent-spec JSON Schema, emitted from the canonical zod `AgentSpecSchema`.
 *
 * This is the SINGLE source of the spec schema for every external consumer (the
 * `agent-applications-spec-schema` MCP tool, any API client). There is no
 * hand-maintained mirror — `spec.ts` is the source of truth and this derives
 * from it, so the schema an author reads can never drift from the one the
 * runner parses.
 *
 * `io: 'input'` emits the WRITE shape — fields with a zod `.default(...)` are
 * optional (you may omit them; the default applies), which is what an author
 * actually submits. Fully inlined (no `$ref`/`$defs`) so every section slice is
 * self-contained and every field's `.describe(...)` travels with it.
 */

import { z } from 'zod'

import { AgentSpecSchema } from './spec'

const FULL_SPEC_JSON_SCHEMA = z.toJSONSchema(AgentSpecSchema, { io: 'input' }) as Record<string, unknown>

const SECTION_PROPS = (FULL_SPEC_JSON_SCHEMA.properties ?? {}) as Record<string, Record<string, unknown>>

/** Top-level spec slices a caller can request one at a time via `section`. */
export const SPEC_SCHEMA_SECTIONS: string[] = Object.keys(SECTION_PROPS)

export interface SpecJsonSchemaResult {
    /** The requested section, or null for the whole spec. */
    section: string | null
    /** A self-contained JSON Schema (inlined, no external refs). */
    spec_json_schema: Record<string, unknown>
}

/**
 * The whole agent-spec JSON Schema, or one top-level section of it (e.g.
 * `models`, `triggers`, `limits`) to save tokens when editing one part.
 * Returns `null` when `section` is given but isn't a real top-level field —
 * callers should reject and surface {@link SPEC_SCHEMA_SECTIONS}.
 */
export function specJsonSchema(section?: string | null): SpecJsonSchemaResult | null {
    if (section) {
        const slice = SECTION_PROPS[section]
        if (!slice) {
            return null
        }
        return {
            section,
            spec_json_schema: { $schema: FULL_SPEC_JSON_SCHEMA.$schema, ...slice },
        }
    }
    return { section: null, spec_json_schema: FULL_SPEC_JSON_SCHEMA }
}
