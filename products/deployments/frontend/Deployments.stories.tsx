import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { DeploymentApi, DeploymentProjectApi } from './generated/api.schemas'

const baseProject: DeploymentProjectApi = {
    id: 'project-1',
    name: 'Site',
    slug: 'site',
    repo_url: 'https://github.com/acme/site',
    default_branch: 'main',
    github_integration_id: null,
    github_repo_id: null,
    build_command: null,
    output_dir: 'dist',
    framework: null,
    inject_posthog_snippet: false,
    cloudflare_project_name: 'team-site',
    subdomain: 'site.pages.dev',
    cloudflare_ready_at: '2026-05-01T00:00:00Z',
    current_deployment: 'd-current',
    is_ready_to_deploy: true,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
}

const docsProject: DeploymentProjectApi = {
    ...baseProject,
    id: 'project-2',
    name: 'Docs',
    slug: 'docs',
    repo_url: 'https://github.com/acme/docs',
    cloudflare_project_name: 'team-docs',
    subdomain: 'docs.pages.dev',
    current_deployment: 'd-docs',
}

const makeDeployment = (id: string, overrides: Partial<DeploymentApi> = {}): DeploymentApi => ({
    id,
    project: 'project-1',
    status: 'ready',
    started_at: '2026-05-13T12:00:00Z',
    finished_at: '2026-05-13T12:01:30Z',
    created_at: '2026-05-13T12:00:00Z',
    commit_sha: id.slice(0, 7),
    commit_message: `commit ${id}`,
    commit_author_name: 'Alice Chen',
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

const currentDeployment = makeDeployment('d-current', {
    is_current: true,
    commit_message: 'feat: deployments list page',
    duration_seconds: 84,
    deployment_url: 'https://acme-site.pages.dev',
})

const docsCurrent = makeDeployment('d-docs', {
    project: 'project-2',
    is_current: true,
    commit_message: 'docs: refresh getting started',
    duration_seconds: 36,
    deployment_url: 'https://acme-docs.pages.dev',
})

const failedDeployment = makeDeployment('d-failed', {
    status: 'error',
    commit_message: 'fix: null author handling',
    commit_author_name: 'Bob Rivera',
    commit_author_email: 'bob@acme.com',
    duration_seconds: 42,
    deployment_url: '',
    error_step: 'build',
    error_message: 'TypeError: cannot read property of undefined in src/utils.ts',
})

const buildingDeployment = makeDeployment('d-building', {
    status: 'building',
    commit_message: 'chore: bump posthog-js to 1.220.0',
    finished_at: null,
    duration_seconds: 0,
    deployment_url: '',
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Deployments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-13',
        pageUrl: urls.deployments(),
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/deployment_projects/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [baseProject, docsProject],
                },
                '/api/projects/:team_id/deployment_projects/project-1/deployments/': {
                    count: 5,
                    next: null,
                    previous: null,
                    results: [
                        currentDeployment,
                        failedDeployment,
                        buildingDeployment,
                        makeDeployment('d-3', { commit_message: 'feat: new card layout' }),
                        makeDeployment('d-4', { commit_message: 'chore: tidy filters' }),
                    ],
                },
                '/api/projects/:team_id/deployment_projects/project-2/deployments/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [docsCurrent],
                },
                '/api/projects/:team_id/deployment_projects/:project_id/deployments/d-current/': currentDeployment,
                '/api/projects/:team_id/deployment_projects/:project_id/deployments/d-docs/': docsCurrent,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// Grid of project cards on /deployments
export const ProjectGrid: Story = {}

// Empty state — onboarding into the product, no projects yet
export const NoProjects: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/deployment_projects/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}

// Single-project grid (current behavior with one connected repo)
export const SingleProjectGrid: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/deployment_projects/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [baseProject],
                },
                '/api/projects/:team_id/deployment_projects/:project_id/deployments/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [currentDeployment],
                },
            },
        }),
    ],
}

// Per-project page: card + table at /deployments/:projectId
export const ProjectPage: Story = {
    parameters: {
        pageUrl: urls.deploymentProject(baseProject.id),
    },
}

// Per-project page where the current deployment failed
export const ProjectPageCurrentErrored: Story = {
    parameters: {
        pageUrl: urls.deploymentProject(baseProject.id),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/deployment_projects/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [baseProject],
                },
                '/api/projects/:team_id/deployment_projects/:project_id/deployments/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [failedDeployment, currentDeployment],
                },
                '/api/projects/:team_id/deployment_projects/:project_id/deployments/d-current/': currentDeployment,
            },
        }),
    ],
}

// Per-project page with zero deployments (just-provisioned project)
export const ProjectPageNoDeployments: Story = {
    parameters: {
        pageUrl: urls.deploymentProject(baseProject.id),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/deployment_projects/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [baseProject],
                },
                '/api/projects/:team_id/deployment_projects/:project_id/deployments/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
            },
        }),
    ],
}

// Deployment detail page at /deployments/:projectId/:deploymentId
export const DeploymentDetail: Story = {
    parameters: {
        pageUrl: urls.deployment(baseProject.id, currentDeployment.id),
    },
}
