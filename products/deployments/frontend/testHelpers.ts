/**
 * Shared fixture factories for deployments tests + stories. Keeps the
 * `DeploymentProjectApi` / `DeploymentApi` shapes in one place so each
 * caller doesn't have to keep its own copy in sync with the generated
 * schemas.
 */
import type { DeploymentApi, DeploymentProjectApi } from './generated/api.schemas'

export const makeProject = (
    id: string,
    name: string,
    overrides: Partial<DeploymentProjectApi> = {}
): DeploymentProjectApi => ({
    id,
    name,
    slug: name.toLowerCase(),
    repo_url: `https://github.com/acme/${name.toLowerCase()}`,
    default_branch: 'main',
    github_integration_id: null,
    github_repo_id: null,
    build_command: null,
    output_dir: 'dist',
    framework: null,
    inject_posthog_snippet: false,
    cloudflare_project_name: `team-${name.toLowerCase()}`,
    subdomain: `${name.toLowerCase()}.pages.dev`,
    cloudflare_ready_at: '2026-05-01T00:00:00Z',
    current_deployment: `${id}-d1`,
    is_ready_to_deploy: true,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
})

export const makeDeployment = (id: string, overrides: Partial<DeploymentApi> = {}): DeploymentApi => ({
    id,
    project: 'project-1',
    status: 'ready',
    started_at: '2026-05-13T12:00:00Z',
    finished_at: '2026-05-13T12:01:30Z',
    created_at: '2026-05-13T12:00:00Z',
    commit_sha: id.slice(0, 7),
    commit_message: `commit ${id}`,
    commit_author_name: 'Alice',
    commit_author_email: 'alice@acme.com',
    repo_url: 'https://github.com/acme/site',
    branch: 'main',
    deployment_url: `https://site-${id}.pages.dev`,
    preview_image_url: '',
    triggered_by_deployment: null,
    triggered_by_user_id: null,
    trigger_kind: 'git',
    error_message: '',
    error_step: '',
    cloudflare_deployment_id: '',
    temporal_workflow_id: '',
    is_current: false,
    duration_seconds: 90,
    ...overrides,
})
