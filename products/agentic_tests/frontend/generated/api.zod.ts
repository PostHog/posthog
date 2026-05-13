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

export const agenticTestsCreateBodyNameMax = 255

export const agenticTestsCreateBodyTargetUrlMax = 2048

export const agenticTestsCreateBodySourceReplayIdMax = 255

export const AgenticTestsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agenticTestsCreateBodyNameMax),
    description: zod.string().optional(),
    target_url: zod.url().max(agenticTestsCreateBodyTargetUrlMax),
    prompt: zod.string().describe('Natural-language instructions for the browser agent.'),
    status: zod
        .enum(['active', 'paused', 'proposed', 'rejected'])
        .optional()
        .describe('\* `active` - Active\n\* `paused` - Paused\n\* `proposed` - Proposed\n\* `rejected` - Rejected'),
    assertions: zod
        .unknown()
        .optional()
        .describe(
            "List of post-run checks the test must satisfy in addition to the agent's own self-evaluation. Each item: {type, ...config}. Supported types: url_contains, event_captured."
        ),
    source_replay_id: zod.string().max(agenticTestsCreateBodySourceReplayIdMax).nullish(),
})

export const agenticTestsUpdateBodyNameMax = 255

export const agenticTestsUpdateBodyTargetUrlMax = 2048

export const agenticTestsUpdateBodySourceReplayIdMax = 255

export const AgenticTestsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agenticTestsUpdateBodyNameMax),
    description: zod.string().optional(),
    target_url: zod.url().max(agenticTestsUpdateBodyTargetUrlMax),
    prompt: zod.string().describe('Natural-language instructions for the browser agent.'),
    status: zod
        .enum(['active', 'paused', 'proposed', 'rejected'])
        .optional()
        .describe('\* `active` - Active\n\* `paused` - Paused\n\* `proposed` - Proposed\n\* `rejected` - Rejected'),
    assertions: zod
        .unknown()
        .optional()
        .describe(
            "List of post-run checks the test must satisfy in addition to the agent's own self-evaluation. Each item: {type, ...config}. Supported types: url_contains, event_captured."
        ),
    source_replay_id: zod.string().max(agenticTestsUpdateBodySourceReplayIdMax).nullish(),
})

export const agenticTestsPartialUpdateBodyNameMax = 255

export const agenticTestsPartialUpdateBodyTargetUrlMax = 2048

export const agenticTestsPartialUpdateBodySourceReplayIdMax = 255

export const AgenticTestsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agenticTestsPartialUpdateBodyNameMax).optional(),
    description: zod.string().optional(),
    target_url: zod.url().max(agenticTestsPartialUpdateBodyTargetUrlMax).optional(),
    prompt: zod.string().optional().describe('Natural-language instructions for the browser agent.'),
    status: zod
        .enum(['active', 'paused', 'proposed', 'rejected'])
        .optional()
        .describe('\* `active` - Active\n\* `paused` - Paused\n\* `proposed` - Proposed\n\* `rejected` - Rejected'),
    assertions: zod
        .unknown()
        .optional()
        .describe(
            "List of post-run checks the test must satisfy in addition to the agent's own self-evaluation. Each item: {type, ...config}. Supported types: url_contains, event_captured."
        ),
    source_replay_id: zod.string().max(agenticTestsPartialUpdateBodySourceReplayIdMax).nullish(),
})
