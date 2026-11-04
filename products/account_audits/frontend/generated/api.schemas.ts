/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface AccountAuditStartRequestApi {
    /** Organization that owns the target team. */
    organization_id: string
    /**
     * Target team ID. Defaults to the non-demo root project with the most distinct resource viewers in the last 30 days, excluding projects pending deletion. Ties use the oldest project.
     * @minimum 1
     */
    team_id?: number
    /**
     * Why the account audit is being requested.
     * @maxLength 500
     */
    reason: string
    /**
     * Project ID containing the skill in this region. Audit credentials authorize reading skills from any project.
     * @minimum 1
     */
    skill_project: number
    /**
     * Name of the single-file skill in skill_project. Uses its latest active version.
     * @maxLength 64
     */
    skill_name: string
}

export interface AccountAuditStartResponseApi {
    /** Native task run executing the account audit. */
    task_run_id: string
    /** Resolved target team ID. */
    team_id: number
}

export interface AccountAuditConflictApi {
    /** Why this audit did not start. */
    detail: string
}
