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
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsCreateBodyNameMax = 200

export const deploymentProjectsCreateBodySlugMax = 80

export const deploymentProjectsCreateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const deploymentProjectsCreateBodyRepoUrlMax = 1024

export const deploymentProjectsCreateBodyDefaultBranchDefault = `main`
export const deploymentProjectsCreateBodyDefaultBranchMax = 255

export const deploymentProjectsCreateBodyGithubPatMax = 500

export const deploymentProjectsCreateBodyBuildCommandDefault = `pnpm install && pnpm build`
export const deploymentProjectsCreateBodyOutputDirDefault = `dist`
export const deploymentProjectsCreateBodyOutputDirMax = 255

export const deploymentProjectsCreateBodyFrameworkMax = 50

export const deploymentProjectsCreateBodyInjectPosthogSnippetDefault = false

export const DeploymentProjectsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(deploymentProjectsCreateBodyNameMax)
        .describe('Human-readable project name shown in the UI.'),
    slug: zod
        .string()
        .max(deploymentProjectsCreateBodySlugMax)
        .regex(deploymentProjectsCreateBodySlugRegExp)
        .describe('URL-safe handle. Becomes the subdomain `{slug}.posthog-app.com`. Must be unique per team.'),
    repo_url: zod
        .url()
        .max(deploymentProjectsCreateBodyRepoUrlMax)
        .describe('HTTPS URL of the source repository this project deploys from.'),
    default_branch: zod
        .string()
        .max(deploymentProjectsCreateBodyDefaultBranchMax)
        .default(deploymentProjectsCreateBodyDefaultBranchDefault)
        .describe('Branch the project deploys from when no commit SHA is pinned. Defaults to `main`.'),
    github_pat: zod
        .string()
        .max(deploymentProjectsCreateBodyGithubPatMax)
        .nullish()
        .describe(
            'GitHub personal access token used to read the repository. Encrypted at rest. Never returned in responses.'
        ),
    build_command: zod
        .string()
        .default(deploymentProjectsCreateBodyBuildCommandDefault)
        .describe('Shell command run inside the build container. Defaults to `pnpm install && pnpm build`.'),
    output_dir: zod
        .string()
        .max(deploymentProjectsCreateBodyOutputDirMax)
        .default(deploymentProjectsCreateBodyOutputDirDefault)
        .describe('Directory containing the built static site, relative to the repository root.'),
    framework: zod
        .string()
        .max(deploymentProjectsCreateBodyFrameworkMax)
        .nullish()
        .describe('Optional framework hint (e.g. `nextjs`, `vite`, `astro`). Null = auto-detect.'),
    inject_posthog_snippet: zod
        .boolean()
        .default(deploymentProjectsCreateBodyInjectPosthogSnippetDefault)
        .describe(
            'If true, the build injects a PostHog snippet into every HTML file that registers `release = deployment_id` as a super-property — runtime exceptions are then linked back to the deployment that introduced them.'
        ),
})

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsCreateBodyCommitShaMax = 64

export const deploymentProjectsDeploymentsCreateBodyBranchMax = 255

export const DeploymentProjectsDeploymentsCreateBody = /* @__PURE__ */ zod
    .object({
        commit_sha: zod
            .string()
            .max(deploymentProjectsDeploymentsCreateBodyCommitShaMax)
            .optional()
            .describe(
                "Optional commit SHA. If omitted, the build worker resolves HEAD of `branch` (or the project's default_branch)."
            ),
        branch: zod
            .string()
            .max(deploymentProjectsDeploymentsCreateBodyBranchMax)
            .optional()
            .describe("Optional branch override. If omitted, uses the project's `default_branch`."),
    })
    .describe('Body of POST \/api\/projects\/{}\/deployment_projects\/{}\/deployments\/.')

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsUpdateBodyNameMax = 200

export const deploymentProjectsUpdateBodySlugMax = 80

export const deploymentProjectsUpdateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const deploymentProjectsUpdateBodyRepoUrlMax = 1024

export const deploymentProjectsUpdateBodyDefaultBranchDefault = `main`
export const deploymentProjectsUpdateBodyDefaultBranchMax = 255

export const deploymentProjectsUpdateBodyGithubPatMax = 500

export const deploymentProjectsUpdateBodyBuildCommandDefault = `pnpm install && pnpm build`
export const deploymentProjectsUpdateBodyOutputDirDefault = `dist`
export const deploymentProjectsUpdateBodyOutputDirMax = 255

export const deploymentProjectsUpdateBodyFrameworkMax = 50

export const deploymentProjectsUpdateBodyInjectPosthogSnippetDefault = false

export const DeploymentProjectsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(deploymentProjectsUpdateBodyNameMax)
        .describe('Human-readable project name shown in the UI.'),
    slug: zod
        .string()
        .max(deploymentProjectsUpdateBodySlugMax)
        .regex(deploymentProjectsUpdateBodySlugRegExp)
        .describe('URL-safe handle. Becomes the subdomain `{slug}.posthog-app.com`. Must be unique per team.'),
    repo_url: zod
        .url()
        .max(deploymentProjectsUpdateBodyRepoUrlMax)
        .describe('HTTPS URL of the source repository this project deploys from.'),
    default_branch: zod
        .string()
        .max(deploymentProjectsUpdateBodyDefaultBranchMax)
        .default(deploymentProjectsUpdateBodyDefaultBranchDefault)
        .describe('Branch the project deploys from when no commit SHA is pinned. Defaults to `main`.'),
    github_pat: zod
        .string()
        .max(deploymentProjectsUpdateBodyGithubPatMax)
        .nullish()
        .describe(
            'GitHub personal access token used to read the repository. Encrypted at rest. Never returned in responses.'
        ),
    build_command: zod
        .string()
        .default(deploymentProjectsUpdateBodyBuildCommandDefault)
        .describe('Shell command run inside the build container. Defaults to `pnpm install && pnpm build`.'),
    output_dir: zod
        .string()
        .max(deploymentProjectsUpdateBodyOutputDirMax)
        .default(deploymentProjectsUpdateBodyOutputDirDefault)
        .describe('Directory containing the built static site, relative to the repository root.'),
    framework: zod
        .string()
        .max(deploymentProjectsUpdateBodyFrameworkMax)
        .nullish()
        .describe('Optional framework hint (e.g. `nextjs`, `vite`, `astro`). Null = auto-detect.'),
    inject_posthog_snippet: zod
        .boolean()
        .default(deploymentProjectsUpdateBodyInjectPosthogSnippetDefault)
        .describe(
            'If true, the build injects a PostHog snippet into every HTML file that registers `release = deployment_id` as a super-property — runtime exceptions are then linked back to the deployment that introduced them.'
        ),
})

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsPartialUpdateBodyNameMax = 200

export const deploymentProjectsPartialUpdateBodySlugMax = 80

export const deploymentProjectsPartialUpdateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const deploymentProjectsPartialUpdateBodyRepoUrlMax = 1024

export const deploymentProjectsPartialUpdateBodyDefaultBranchDefault = `main`
export const deploymentProjectsPartialUpdateBodyDefaultBranchMax = 255

export const deploymentProjectsPartialUpdateBodyGithubPatMax = 500

export const deploymentProjectsPartialUpdateBodyBuildCommandDefault = `pnpm install && pnpm build`
export const deploymentProjectsPartialUpdateBodyOutputDirDefault = `dist`
export const deploymentProjectsPartialUpdateBodyOutputDirMax = 255

export const deploymentProjectsPartialUpdateBodyFrameworkMax = 50

export const deploymentProjectsPartialUpdateBodyInjectPosthogSnippetDefault = false

export const DeploymentProjectsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(deploymentProjectsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable project name shown in the UI.'),
    slug: zod
        .string()
        .max(deploymentProjectsPartialUpdateBodySlugMax)
        .regex(deploymentProjectsPartialUpdateBodySlugRegExp)
        .optional()
        .describe('URL-safe handle. Becomes the subdomain `{slug}.posthog-app.com`. Must be unique per team.'),
    repo_url: zod
        .url()
        .max(deploymentProjectsPartialUpdateBodyRepoUrlMax)
        .optional()
        .describe('HTTPS URL of the source repository this project deploys from.'),
    default_branch: zod
        .string()
        .max(deploymentProjectsPartialUpdateBodyDefaultBranchMax)
        .default(deploymentProjectsPartialUpdateBodyDefaultBranchDefault)
        .describe('Branch the project deploys from when no commit SHA is pinned. Defaults to `main`.'),
    github_pat: zod
        .string()
        .max(deploymentProjectsPartialUpdateBodyGithubPatMax)
        .nullish()
        .describe(
            'GitHub personal access token used to read the repository. Encrypted at rest. Never returned in responses.'
        ),
    build_command: zod
        .string()
        .default(deploymentProjectsPartialUpdateBodyBuildCommandDefault)
        .describe('Shell command run inside the build container. Defaults to `pnpm install && pnpm build`.'),
    output_dir: zod
        .string()
        .max(deploymentProjectsPartialUpdateBodyOutputDirMax)
        .default(deploymentProjectsPartialUpdateBodyOutputDirDefault)
        .describe('Directory containing the built static site, relative to the repository root.'),
    framework: zod
        .string()
        .max(deploymentProjectsPartialUpdateBodyFrameworkMax)
        .nullish()
        .describe('Optional framework hint (e.g. `nextjs`, `vite`, `astro`). Null = auto-detect.'),
    inject_posthog_snippet: zod
        .boolean()
        .default(deploymentProjectsPartialUpdateBodyInjectPosthogSnippetDefault)
        .describe(
            'If true, the build injects a PostHog snippet into every HTML file that registers `release = deployment_id` as a super-property — runtime exceptions are then linked back to the deployment that introduced them.'
        ),
})
