import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { Scene } from 'scenes/sceneTypes'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { deploymentLogic } from './deploymentLogic'
import { deploymentsLogic } from './deploymentsLogic'
import type { DeploymentApi, DeploymentProjectApi } from './generated/api.schemas'

const project: DeploymentProjectApi = {
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
    current_deployment: 'dep-current',
    is_ready_to_deploy: true,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
}

const deployments: DeploymentApi[] = [
    {
        id: 'dep-current',
        project: project.id,
        status: 'ready',
        started_at: '2026-05-13T12:00:00Z',
        finished_at: '2026-05-13T12:01:30Z',
        created_at: '2026-05-13T12:00:00Z',
        commit_sha: '7a3f9c2',
        commit_message: 'feat: ship deployments',
        commit_author_name: 'Alice',
        commit_author_email: 'alice@acme.com',
        repo_url: 'https://github.com/acme/site',
        branch: 'main',
        deployment_url: 'https://site-dep-current.pages.dev',
        preview_image_url: '',
        triggered_by_deployment: null,
        triggered_by_user_id: null,
        trigger_kind: 'git',
        error_message: '',
        error_step: '',
        cloudflare_deployment_id: 'cf-1',
        temporal_workflow_id: '',
        is_current: true,
        duration_seconds: 90,
    },
]

describe('deploymentLogic', () => {
    let listLogic: ReturnType<typeof deploymentsLogic.build>

    beforeEach(async () => {
        initKeaTests()

        useMocks({
            get: {
                '/api/projects/:team/deployment_projects/': () => [
                    200,
                    { count: 1, next: null, previous: null, results: [project] },
                ],
                '/api/projects/:team/deployment_projects/:project_id/deployments/': () => [
                    200,
                    { count: deployments.length, next: null, previous: null, results: deployments },
                ],
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/': (req) => {
                    const found = deployments.find((d) => d.id === String(req.params.id))
                    return found ? [200, found] : [404, { detail: 'Not found' }]
                },
            },
        })

        router.actions.push('/deployments')

        listLogic = deploymentsLogic()
        listLogic.mount()
        await expectLogic(listLogic).toFinishAllListeners()
    })

    afterEach(() => {
        listLogic?.unmount()
    })

    it('fetches the deployment by id from the retrieve endpoint', async () => {
        const detail = deploymentLogic({ id: 'dep-current' })
        detail.mount()
        try {
            await expectLogic(detail).toFinishAllListeners()
            expect(detail.values.deployment?.id).toEqual('dep-current')
            expect(detail.values.deployment?.commit_message).toEqual('feat: ship deployments')
            expect(detail.values.deploymentMissing).toBe(false)
        } finally {
            detail.unmount()
        }
    })

    it('flags deploymentMissing once the retrieve returns 404', async () => {
        const detail = deploymentLogic({ id: 'does-not-exist' })
        detail.mount()
        try {
            await expectLogic(detail).toFinishAllListeners()
            expect(detail.values.deploymentLoading).toBe(false)
            expect(detail.values.deployment).toBeNull()
            expect(detail.values.deploymentMissing).toBe(true)
        } finally {
            detail.unmount()
        }
    })

    it('builds breadcrumbs: Deployments → commit message (or id when missing)', async () => {
        const found = deploymentLogic({ id: 'dep-current' })
        found.mount()
        try {
            await expectLogic(found).toFinishAllListeners()
            const crumbs = found.values.breadcrumbs
            expect(crumbs).toHaveLength(2)
            expect(crumbs[0]).toMatchObject({ key: Scene.Deployments, name: 'Deployments' })
            expect(crumbs[1]).toMatchObject({ name: 'feat: ship deployments' })
        } finally {
            found.unmount()
        }

        const missing = deploymentLogic({ id: 'does-not-exist' })
        missing.mount()
        try {
            await expectLogic(missing).toFinishAllListeners()
            const crumbs = missing.values.breadcrumbs
            // Falls back to 'Deployment' literal when retrieve returns no row.
            expect(crumbs[1]).toMatchObject({ name: 'Deployment' })
        } finally {
            missing.unmount()
        }
    })

    it('deep-link: loads the deployment once projects finish loading', async () => {
        // Simulate a cold start — the list logic has not been mounted yet, so
        // selectedProjectId is null when deploymentLogic mounts.
        listLogic.unmount()
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/deployment_projects/': () => [
                    200,
                    { count: 1, next: null, previous: null, results: [project] },
                ],
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/': (req) => {
                    const found = deployments.find((d) => d.id === String(req.params.id))
                    return found ? [200, found] : [404, { detail: 'Not found' }]
                },
            },
        })

        const detail = deploymentLogic({ id: 'dep-current' })
        detail.mount()
        try {
            await expectLogic(detail).toFinishAllListeners()
            expect(detail.values.deployment?.id).toEqual('dep-current')
            expect(detail.values.deploymentMissing).toBe(false)
        } finally {
            detail.unmount()
        }
    })
})
