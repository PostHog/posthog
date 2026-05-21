/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const DeploymentStatusEnumApi = zod
    .enum(['queued', 'initializing', 'building', 'ready', 'error', 'cancelled'])
    .describe(
        '\* `queued` - Queued\n\* `initializing` - Initializing\n\* `building` - Building\n\* `ready` - Ready\n\* `error` - Error\n\* `cancelled` - Cancelled'
    )

export type DeploymentStatusEnumApi = zod.input<typeof DeploymentStatusEnumApi>
export type DeploymentStatusEnumApiOutput = zod.output<typeof DeploymentStatusEnumApi>

export const TriggerKindEnumApi = zod
    .enum(['git', 'redeploy', 'rollback', 'seed'])
    .describe('\* `git` - Git\n\* `redeploy` - Redeploy\n\* `rollback` - Rollback\n\* `seed` - Seed')

export type TriggerKindEnumApi = zod.input<typeof TriggerKindEnumApi>
export type TriggerKindEnumApiOutput = zod.output<typeof TriggerKindEnumApi>

export const deploymentApiCommitShaMax = 64

export const deploymentApiCommitAuthorNameMax = 255

export const deploymentApiCommitAuthorEmailMax = 255

export const deploymentApiRepoUrlMax = 1024

export const deploymentApiBranchMax = 255

export const deploymentApiDeploymentUrlMax = 1024

export const deploymentApiPreviewImageUrlMax = 1024

export const DeploymentApi = zod.object({
    id: zod.uuid().describe('Unique identifier for the deployment.'),
    status: zod
        .enum(['queued', 'initializing', 'building', 'ready', 'error', 'cancelled'])
        .describe(
            '\* `queued` - Queued\n\* `initializing` - Initializing\n\* `building` - Building\n\* `ready` - Ready\n\* `error` - Error\n\* `cancelled` - Cancelled'
        )
        .describe(
            'Current pipeline stage for the deployment. Valid values: queued, initializing, building, ready, error, cancelled.\n\n\* `queued` - Queued\n\* `initializing` - Initializing\n\* `building` - Building\n\* `ready` - Ready\n\* `error` - Error\n\* `cancelled` - Cancelled'
        ),
    started_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Timestamp when the pipeline started building. Null while still queued.'),
    finished_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Timestamp when the pipeline finished (regardless of outcome). Null while still running.'),
    created_at: zod.iso.datetime({ offset: true }).describe('Timestamp when the deployment row was created.'),
    commit_sha: zod
        .string()
        .max(deploymentApiCommitShaMax)
        .optional()
        .describe('Git commit SHA the deployment was built from. Empty for non-git triggers.'),
    commit_message: zod.string().optional().describe('Commit message associated with the commit SHA.'),
    commit_author_name: zod
        .string()
        .max(deploymentApiCommitAuthorNameMax)
        .optional()
        .describe('Display name of the commit author.'),
    commit_author_email: zod
        .string()
        .max(deploymentApiCommitAuthorEmailMax)
        .optional()
        .describe('Email address of the commit author.'),
    repo_url: zod
        .url()
        .max(deploymentApiRepoUrlMax)
        .optional()
        .describe('HTTPS URL of the source repository this deployment came from.'),
    branch: zod
        .string()
        .max(deploymentApiBranchMax)
        .optional()
        .describe('Source branch the deployment was built from.'),
    deployment_url: zod
        .url()
        .max(deploymentApiDeploymentUrlMax)
        .optional()
        .describe('Public URL where the built site is served once the deployment is ready.'),
    preview_image_url: zod
        .url()
        .max(deploymentApiPreviewImageUrlMax)
        .optional()
        .describe('URL of a screenshot capture of the deployed site, used in the list view.'),
    triggered_by_deployment: zod
        .uuid()
        .nullable()
        .describe('The deployment this one was triggered from (e.g. for rollbacks\/redeploys).'),
    trigger_kind: zod
        .enum(['git', 'redeploy', 'rollback', 'seed'])
        .describe('\* `git` - Git\n\* `redeploy` - Redeploy\n\* `rollback` - Rollback\n\* `seed` - Seed')
        .describe(
            'What caused this deployment to start. One of: git, redeploy, rollback, seed.\n\n\* `git` - Git\n\* `redeploy` - Redeploy\n\* `rollback` - Rollback\n\* `seed` - Seed'
        ),
    is_current: zod
        .boolean()
        .describe("Whether this deployment is the team's currently-serving production deployment."),
    duration_seconds: zod
        .number()
        .describe('Build duration in seconds (finished_at - started_at). 0 while still running.'),
})

export type DeploymentApi = zod.input<typeof DeploymentApi>
export type DeploymentApiOutput = zod.output<typeof DeploymentApi>

export const paginatedDeploymentListApiResultsItemCommitShaMax = 64

export const paginatedDeploymentListApiResultsItemCommitAuthorNameMax = 255

export const paginatedDeploymentListApiResultsItemCommitAuthorEmailMax = 255

export const paginatedDeploymentListApiResultsItemRepoUrlMax = 1024

export const paginatedDeploymentListApiResultsItemBranchMax = 255

export const paginatedDeploymentListApiResultsItemDeploymentUrlMax = 1024

export const paginatedDeploymentListApiResultsItemPreviewImageUrlMax = 1024

export const PaginatedDeploymentListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid().describe('Unique identifier for the deployment.'),
            status: zod
                .enum(['queued', 'initializing', 'building', 'ready', 'error', 'cancelled'])
                .describe(
                    '\* `queued` - Queued\n\* `initializing` - Initializing\n\* `building` - Building\n\* `ready` - Ready\n\* `error` - Error\n\* `cancelled` - Cancelled'
                )
                .describe(
                    'Current pipeline stage for the deployment. Valid values: queued, initializing, building, ready, error, cancelled.\n\n\* `queued` - Queued\n\* `initializing` - Initializing\n\* `building` - Building\n\* `ready` - Ready\n\* `error` - Error\n\* `cancelled` - Cancelled'
                ),
            started_at: zod.iso
                .datetime({ offset: true })
                .nullish()
                .describe('Timestamp when the pipeline started building. Null while still queued.'),
            finished_at: zod.iso
                .datetime({ offset: true })
                .nullish()
                .describe('Timestamp when the pipeline finished (regardless of outcome). Null while still running.'),
            created_at: zod.iso.datetime({ offset: true }).describe('Timestamp when the deployment row was created.'),
            commit_sha: zod
                .string()
                .max(paginatedDeploymentListApiResultsItemCommitShaMax)
                .optional()
                .describe('Git commit SHA the deployment was built from. Empty for non-git triggers.'),
            commit_message: zod.string().optional().describe('Commit message associated with the commit SHA.'),
            commit_author_name: zod
                .string()
                .max(paginatedDeploymentListApiResultsItemCommitAuthorNameMax)
                .optional()
                .describe('Display name of the commit author.'),
            commit_author_email: zod
                .string()
                .max(paginatedDeploymentListApiResultsItemCommitAuthorEmailMax)
                .optional()
                .describe('Email address of the commit author.'),
            repo_url: zod
                .url()
                .max(paginatedDeploymentListApiResultsItemRepoUrlMax)
                .optional()
                .describe('HTTPS URL of the source repository this deployment came from.'),
            branch: zod
                .string()
                .max(paginatedDeploymentListApiResultsItemBranchMax)
                .optional()
                .describe('Source branch the deployment was built from.'),
            deployment_url: zod
                .url()
                .max(paginatedDeploymentListApiResultsItemDeploymentUrlMax)
                .optional()
                .describe('Public URL where the built site is served once the deployment is ready.'),
            preview_image_url: zod
                .url()
                .max(paginatedDeploymentListApiResultsItemPreviewImageUrlMax)
                .optional()
                .describe('URL of a screenshot capture of the deployed site, used in the list view.'),
            triggered_by_deployment: zod
                .uuid()
                .nullable()
                .describe('The deployment this one was triggered from (e.g. for rollbacks\/redeploys).'),
            trigger_kind: zod
                .enum(['git', 'redeploy', 'rollback', 'seed'])
                .describe('\* `git` - Git\n\* `redeploy` - Redeploy\n\* `rollback` - Rollback\n\* `seed` - Seed')
                .describe(
                    'What caused this deployment to start. One of: git, redeploy, rollback, seed.\n\n\* `git` - Git\n\* `redeploy` - Redeploy\n\* `rollback` - Rollback\n\* `seed` - Seed'
                ),
            is_current: zod
                .boolean()
                .describe("Whether this deployment is the team's currently-serving production deployment."),
            duration_seconds: zod
                .number()
                .describe('Build duration in seconds (finished_at - started_at). 0 while still running.'),
        })
    ),
})

export type PaginatedDeploymentListApi = zod.input<typeof PaginatedDeploymentListApi>
export type PaginatedDeploymentListApiOutput = zod.output<typeof PaginatedDeploymentListApi>

export const DeploymentActionResponseApi = zod
    .object({
        detail: zod.string().describe('Human-readable explanation of the stub response.'),
    })
    .describe('Response shape for the redeploy\/rollback\/refresh-preview stubs.')

export type DeploymentActionResponseApi = zod.input<typeof DeploymentActionResponseApi>
export type DeploymentActionResponseApiOutput = zod.output<typeof DeploymentActionResponseApi>
