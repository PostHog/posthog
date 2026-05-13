/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 *
 * NOTE: This is a placeholder shipped with the Deployments scaffold so the
 * TypeScript build passes before `hogli build:openapi` has been run. The
 * next run of `hogli build:openapi` will overwrite this file with the real
 * generated types.
 */

export type DeploymentStatusEnumApi =
    | 'queued'
    | 'initializing'
    | 'building'
    | 'ready'
    | 'error'
    | 'cancelled'

export type DeploymentTriggerKindEnumApi = 'git' | 'redeploy' | 'rollback' | 'seed'

export interface DeploymentApi {
    id: string
    status: DeploymentStatusEnumApi
    started_at: string | null
    finished_at: string | null
    created_at: string
    commit_sha: string
    commit_message: string
    commit_author_name: string
    commit_author_email: string
    repo_url: string
    branch: string
    deployment_url: string
    preview_image_url: string
    triggered_by_deployment: string | null
    trigger_kind: DeploymentTriggerKindEnumApi
    is_current: boolean
    duration_seconds: number
}

export interface PaginatedDeploymentListApi {
    count: number
    next: string | null
    previous: string | null
    results: DeploymentApi[]
}
