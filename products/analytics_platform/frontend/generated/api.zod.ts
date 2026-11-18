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
 * Marks the team's READY precompute jobs stale so the next read recomputes them, e.g. after a source resync changed the underlying data. Optionally scoped to a single query hash. PENDING jobs are left alone: anything in flight is already computing against current data.
 * @summary Invalidate stored precompute for this team (staff only)
 */
export const precomputeDebugInvalidateBodyQueryHashMax = 64

export const PrecomputeDebugInvalidateBody = /* @__PURE__ */ zod.object({
    query_hash: zod
        .string()
        .max(precomputeDebugInvalidateBodyQueryHashMax)
        .nullish()
        .describe('Only invalidate jobs for this query hash. Omit to invalidate every hash stored for the team.'),
})
