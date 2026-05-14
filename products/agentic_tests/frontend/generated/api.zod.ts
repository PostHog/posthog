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

export const agenticTestsCreateBodyScheduleCronMax = 128

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
            "List of post-run checks the test must satisfy, scoped to the agent's own PostHog session. Each item: {type, ...config}. Supported types: event_captured, event_not_captured, no_console_errors."
        ),
    schedule_cron: zod
        .string()
        .max(agenticTestsCreateBodyScheduleCronMax)
        .optional()
        .describe(
            'Cron expression (5 fields, UTC) describing the run cadence. Empty means manual-only — no automatic runs.'
        ),
    regions: zod
        .unknown()
        .optional()
        .describe(
            'List of Browserbase regions the test may run from. Each run picks one at random. Empty list means use the Browserbase default (us-west-2). Supported: us-west-2, us-east-1, eu-central-1, ap-southeast-1.'
        ),
    source_replay_id: zod.string().max(agenticTestsCreateBodySourceReplayIdMax).nullish(),
})

export const agenticTestsUpdateBodyNameMax = 255

export const agenticTestsUpdateBodyTargetUrlMax = 2048

export const agenticTestsUpdateBodyScheduleCronMax = 128

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
            "List of post-run checks the test must satisfy, scoped to the agent's own PostHog session. Each item: {type, ...config}. Supported types: event_captured, event_not_captured, no_console_errors."
        ),
    schedule_cron: zod
        .string()
        .max(agenticTestsUpdateBodyScheduleCronMax)
        .optional()
        .describe(
            'Cron expression (5 fields, UTC) describing the run cadence. Empty means manual-only — no automatic runs.'
        ),
    regions: zod
        .unknown()
        .optional()
        .describe(
            'List of Browserbase regions the test may run from. Each run picks one at random. Empty list means use the Browserbase default (us-west-2). Supported: us-west-2, us-east-1, eu-central-1, ap-southeast-1.'
        ),
    source_replay_id: zod.string().max(agenticTestsUpdateBodySourceReplayIdMax).nullish(),
})

export const agenticTestsPartialUpdateBodyNameMax = 255

export const agenticTestsPartialUpdateBodyTargetUrlMax = 2048

export const agenticTestsPartialUpdateBodyScheduleCronMax = 128

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
            "List of post-run checks the test must satisfy, scoped to the agent's own PostHog session. Each item: {type, ...config}. Supported types: event_captured, event_not_captured, no_console_errors."
        ),
    schedule_cron: zod
        .string()
        .max(agenticTestsPartialUpdateBodyScheduleCronMax)
        .optional()
        .describe(
            'Cron expression (5 fields, UTC) describing the run cadence. Empty means manual-only — no automatic runs.'
        ),
    regions: zod
        .unknown()
        .optional()
        .describe(
            'List of Browserbase regions the test may run from. Each run picks one at random. Empty list means use the Browserbase default (us-west-2). Supported: us-west-2, us-east-1, eu-central-1, ap-southeast-1.'
        ),
    source_replay_id: zod.string().max(agenticTestsPartialUpdateBodySourceReplayIdMax).nullish(),
})

/**
 * Launch a sandboxed agent to analyze a GitHub repository and propose test flows.
 */
export const agenticTestsDetectFlowsCreateBodyRepositoryMax = 256

export const agenticTestsDetectFlowsCreateBodyDomainMax = 256

export const AgenticTestsDetectFlowsCreateBody = /* @__PURE__ */ zod.object({
    repository: zod
        .string()
        .max(agenticTestsDetectFlowsCreateBodyRepositoryMax)
        .describe("GitHub repository in 'owner\/repo' format, e.g. 'posthog\/posthog-js'."),
    domain: zod
        .string()
        .max(agenticTestsDetectFlowsCreateBodyDomainMax)
        .describe("Domain where the product is deployed, e.g. 'us.posthog.com'."),
})
