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

export const accountAuditsStartCreateBodyReasonMax = 500

export const accountAuditsStartCreateBodySkillNameMax = 64

export const AccountAuditsStartCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization that owns the target team.'),
    team_id: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Target team ID. Defaults to the non-demo root project with the most distinct resource viewers in the last 30 days, excluding projects pending deletion. Ties use the oldest project.'
        ),
    reason: zod
        .string()
        .max(accountAuditsStartCreateBodyReasonMax)
        .describe('Why the account audit is being requested.'),
    skill_project: zod
        .number()
        .min(1)
        .describe(
            'Project ID containing the skill in this region. Audit credentials authorize reading skills from any project.'
        ),
    skill_name: zod
        .string()
        .max(accountAuditsStartCreateBodySkillNameMax)
        .describe('Name of the single-file skill in skill_project. Uses its latest active version.'),
})
