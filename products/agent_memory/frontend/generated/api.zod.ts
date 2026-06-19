/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Append or replace a single markdown section atomically — never clobbers concurrent edits.
 */
export const agentMemoryAppendCreateBodyPathMax = 1024

export const agentMemoryAppendCreateBodyHeadingMax = 500

export const agentMemoryAppendCreateBodyBodyMax = 1000000

export const AgentMemoryAppendCreateBody = /* @__PURE__ */ zod.object({
    path: zod
        .string()
        .max(agentMemoryAppendCreateBodyPathMax)
        .describe("Relative path of the file to append to, e.g. 'project.md'. Created if it does not exist."),
    heading: zod
        .string()
        .max(agentMemoryAppendCreateBodyHeadingMax)
        .describe(
            "Section title (without leading '#'). If a section with this title already exists, its body is replaced; otherwise a new '## {heading}' section is appended."
        ),
    body: zod
        .string()
        .max(agentMemoryAppendCreateBodyBodyMax)
        .describe('Markdown body for the section. Never clobbers other sections of the file.'),
})

/**
 * Compare-and-set write of a whole file. Returns 409 on a version mismatch.
 */
export const agentMemoryWriteCreateBodyPathMax = 1024

export const agentMemoryWriteCreateBodyContentMax = 1000000

export const AgentMemoryWriteCreateBody = /* @__PURE__ */ zod.object({
    path: zod
        .string()
        .max(agentMemoryWriteCreateBodyPathMax)
        .describe(
            "Relative path of the file to write, e.g. 'project.md' or 'users\/jane-doe.md'. Must end in '.md', may not contain '..' or absolute segments."
        ),
    content: zod
        .string()
        .max(agentMemoryWriteCreateBodyContentMax)
        .describe(
            "Full markdown body to store. Replaces the file's content entirely — prefer the append endpoint to add a section without clobbering concurrent edits."
        ),
    expected_version: zod
        .number()
        .nullish()
        .describe(
            'Compare-and-set token. Omit (or null) to create a new file; pass the version you last read to update an existing one. A mismatch returns 409 — re-read and merge before retrying.'
        ),
})
