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
export const deploymentProjectsCreateBodyDefaultBranchMax = 255

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
    default_branch: zod
        .string()
        .max(deploymentProjectsCreateBodyDefaultBranchMax)
        .optional()
        .describe('Branch PostHog tracks for deployment updates. Defaults to the repository default branch.'),
    github_integration_id: zod.number().describe('Existing PostHog GitHub integration id used for repository access.'),
    github_repo_id: zod
        .number()
        .describe("Stable GitHub repository identifier selected from the existing integration's repository list."),
    build_command: zod
        .string()
        .nullish()
        .describe(
            'Optional shell command run inside the build container. Null = the build worker infers it from `framework` (or auto-detection if framework is also null).'
        ),
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
export const deploymentProjectsUpdateBodyDefaultBranchMax = 255

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
        .describe(
            'URL-safe handle. Combined with the team id to form the Cloudflare project name; the actual subdomain comes from Cloudflare and is returned in the read-only `subdomain` field. Must be unique per team.'
        ),
    default_branch: zod
        .string()
        .max(deploymentProjectsUpdateBodyDefaultBranchMax)
        .optional()
        .describe('Branch PostHog tracks for deployment updates. Defaults to the repository default branch.'),
    github_integration_id: zod
        .number()
        .nullish()
        .describe('Existing PostHog GitHub integration id used for repository access.'),
    github_repo_id: zod
        .number()
        .nullish()
        .describe("Stable GitHub repository identifier selected from the existing integration's repository list."),
    build_command: zod
        .string()
        .nullish()
        .describe(
            'Optional shell command run inside the build container. Null = the build worker infers it from `framework` (or auto-detection if framework is also null).'
        ),
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
export const deploymentProjectsPartialUpdateBodyDefaultBranchMax = 255

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
        .describe(
            'URL-safe handle. Combined with the team id to form the Cloudflare project name; the actual subdomain comes from Cloudflare and is returned in the read-only `subdomain` field. Must be unique per team.'
        ),
    default_branch: zod
        .string()
        .max(deploymentProjectsPartialUpdateBodyDefaultBranchMax)
        .optional()
        .describe('Branch PostHog tracks for deployment updates. Defaults to the repository default branch.'),
    github_integration_id: zod
        .number()
        .nullish()
        .describe('Existing PostHog GitHub integration id used for repository access.'),
    github_repo_id: zod
        .number()
        .nullish()
        .describe("Stable GitHub repository identifier selected from the existing integration's repository list."),
    build_command: zod
        .string()
        .nullish()
        .describe(
            'Optional shell command run inside the build container. Null = the build worker infers it from `framework` (or auto-detection if framework is also null).'
        ),
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

/**
 * Pure inspection — no git access, no DB writes. The connect-repo UI calls this after fetching `package.json` (via the team's GitHub integration) and uses the response to prefill the form.
 * @summary Suggest project config from a repo's package.json and lockfiles
 */
export const deploymentProjectsDetectCreateBodyLockfilesItemMax = 64

export const DeploymentProjectsDetectCreateBody = /* @__PURE__ */ zod
    .object({
        package_json: zod
            .unknown()
            .optional()
            .describe(
                "Parsed contents of the repo's `package.json`. Pass null or omit if the repo doesn't have one — the response is then the plain-HTML fallback."
            ),
        lockfiles: zod
            .array(zod.string().max(deploymentProjectsDetectCreateBodyLockfilesItemMax))
            .optional()
            .describe(
                'Filenames of package-manager lockfiles found in the repo root (e.g. [\"pnpm-lock.yaml\"]). Used to pick the package manager.'
            ),
    })
    .describe(
        "Inputs the `\/detect\/` endpoint needs to suggest a project config.\n\nDecouples detection from any one git provider — callers fetch\n`package.json` and the list of lockfiles however they like (GitHub\nraw content via the team's existing integration, a temporary clone,\nuser-pasted JSON during early development) and pass them here."
    )
