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
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Land agent commits from a git bundle
 */
export const contextLayerCommitsCreateBodySummaryMax = 10000

export const contextLayerCommitsCreateBodyBranchMax = 64

export const ContextLayerCommitsCreateBody = /* @__PURE__ */ zod
    .object({
        bundle: zod
            .url()
            .describe(
                "A `git bundle` carrying the ref to land, created in the agent's clone (for example `git bundle create out.bundle origin\/main..main`)."
            ),
        summary: zod
            .string()
            .max(contextLayerCommitsCreateBodySummaryMax)
            .optional()
            .describe('Optional run summary stored in the landed commit body.'),
        branch: zod
            .string()
            .max(contextLayerCommitsCreateBodyBranchMax)
            .nullish()
            .describe(
                'Land a dated dreaming branch (`dream\/<YYYY-MM-DD>`) as one merge commit instead of rebasing onto `main`. Omit for ordinary commits on `main`.'
            ),
    })
    .describe('Request body for landing agent commits posted back as a git bundle.')

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Create or replace a wiki page
 */
export const contextLayerPagesUpdateBodyPathMax = 512

export const contextLayerPagesUpdateBodyContentMax = 1000000

export const ContextLayerPagesUpdateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(contextLayerPagesUpdateBodyPathMax)
            .describe(
                "Repo-relative Markdown path inside the wiki's structure, for example `projects\/12\/spaces\/general.md`."
            ),
        content: zod
            .string()
            .max(contextLayerPagesUpdateBodyContentMax)
            .describe('The complete Markdown content for the page.'),
        base_head: zod
            .string()
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the head sha the edit is based on. A moved head is rejected with 409 and the current head; omit to write unguarded.'
            ),
    })
    .describe('Request body for creating or replacing one wiki page.')

/**
 * The same organization wiki, reached by an agent run inside a sandbox.
 *
 * This exists as a second, project-nested route because a sandbox run token
 * carries `scoped_teams`, and `APIScopePermission` accepts those only on a
 * project-nested view — on the organization-scoped route above, every sandbox
 * token is refused before it reaches any of this. The wiki is still one repo
 * per organization; the project in the path is how a run token proves which
 * organization it may act for, and is not a scope on the wiki itself.
 * @summary Land agent commits from a git bundle
 */
export const contextLayerAgentCommitsCreateBodySummaryMax = 10000

export const contextLayerAgentCommitsCreateBodyBranchMax = 64

export const ContextLayerAgentCommitsCreateBody = /* @__PURE__ */ zod
    .object({
        bundle: zod
            .url()
            .describe(
                "A `git bundle` carrying the ref to land, created in the agent's clone (for example `git bundle create out.bundle origin\/main..main`)."
            ),
        summary: zod
            .string()
            .max(contextLayerAgentCommitsCreateBodySummaryMax)
            .optional()
            .describe('Optional run summary stored in the landed commit body.'),
        branch: zod
            .string()
            .max(contextLayerAgentCommitsCreateBodyBranchMax)
            .nullish()
            .describe(
                'Land a dated dreaming branch (`dream\/<YYYY-MM-DD>`) as one merge commit instead of rebasing onto `main`. Omit for ordinary commits on `main`.'
            ),
    })
    .describe('Request body for landing agent commits posted back as a git bundle.')

/**
 * The same organization wiki, reached by an agent run inside a sandbox.
 *
 * This exists as a second, project-nested route because a sandbox run token
 * carries `scoped_teams`, and `APIScopePermission` accepts those only on a
 * project-nested view — on the organization-scoped route above, every sandbox
 * token is refused before it reaches any of this. The wiki is still one repo
 * per organization; the project in the path is how a run token proves which
 * organization it may act for, and is not a scope on the wiki itself.
 * @summary Create or replace a wiki page
 */
export const contextLayerAgentPagesUpdateBodyPathMax = 512

export const contextLayerAgentPagesUpdateBodyContentMax = 1000000

export const ContextLayerAgentPagesUpdateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(contextLayerAgentPagesUpdateBodyPathMax)
            .describe(
                "Repo-relative Markdown path inside the wiki's structure, for example `projects\/12\/spaces\/general.md`."
            ),
        content: zod
            .string()
            .max(contextLayerAgentPagesUpdateBodyContentMax)
            .describe('The complete Markdown content for the page.'),
        base_head: zod
            .string()
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the head sha the edit is based on. A moved head is rejected with 409 and the current head; omit to write unguarded.'
            ),
    })
    .describe('Request body for creating or replacing one wiki page.')
