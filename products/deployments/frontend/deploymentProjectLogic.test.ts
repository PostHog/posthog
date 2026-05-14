import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { deploymentProjectLogic } from './deploymentProjectLogic'
import { deploymentsLogic } from './deploymentsLogic'
import type { DeploymentApi, DeploymentProjectApi } from './generated/api.schemas'

const projectA: DeploymentProjectApi = {
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
    current_deployment: 'project-1-d1',
    is_ready_to_deploy: true,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
}

const makeDeployment = (id: string, overrides: Partial<DeploymentApi> = {}): DeploymentApi => ({
    id,
    project: projectA.id,
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

describe('deploymentProjectLogic', () => {
    let listLogic: ReturnType<typeof deploymentsLogic.build>
    let logic: ReturnType<typeof deploymentProjectLogic.build>
    let lastDeploymentsRequestUrl: string | null

    beforeEach(async () => {
        initKeaTests()
        lastDeploymentsRequestUrl = null

        useMocks({
            get: {
                '/api/projects/:team/deployment_projects/': () => [
                    200,
                    { count: 1, next: null, previous: null, results: [projectA] },
                ],
                '/api/projects/:team/deployment_projects/:project_id/deployments/': (req) => {
                    lastDeploymentsRequestUrl = req.url.toString()
                    return [
                        200,
                        {
                            count: 1,
                            next: null,
                            previous: null,
                            results: [
                                makeDeployment(`${req.params.project_id}-d1`, {
                                    project: String(req.params.project_id),
                                    is_current: true,
                                }),
                            ],
                        },
                    ]
                },
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/': (req) => [
                    200,
                    makeDeployment(String(req.params.id), {
                        project: String(req.params.project_id),
                        is_current: true,
                    }),
                ],
            },
            post: {
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/redeploy/': () => [
                    201,
                    makeDeployment('new-redeploy', { status: 'queued', trigger_kind: 'redeploy' }),
                ],
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/rollback/': () => [
                    201,
                    makeDeployment('new-rollback', { status: 'ready', trigger_kind: 'rollback' }),
                ],
            },
        })

        router.actions.push(`/deployments/${projectA.id}`)

        listLogic = deploymentsLogic()
        listLogic.mount()
        await expectLogic(listLogic).toFinishAllListeners()

        logic = deploymentProjectLogic({ projectId: projectA.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
        listLogic?.unmount()
    })

    it('loads deployments and current deployment for its project on mount', () => {
        expect(logic.values.deployments).toHaveLength(1)
        expect(logic.values.deployments[0]?.project).toEqual(projectA.id)
        expect(logic.values.currentDeployment?.is_current).toBe(true)
    })

    it('forwards status/author/search to the backend as query params', async () => {
        await expectLogic(logic, () => {
            logic.actions.setFilters({
                search: 'feat: add',
                status: ['ready', 'error'],
                author: 'alice@acme.com',
            })
        }).toFinishAllListeners()

        expect(lastDeploymentsRequestUrl).not.toBeNull()
        const url = new URL(lastDeploymentsRequestUrl!)
        expect(url.searchParams.get('search')).toEqual('feat: add')
        expect(url.searchParams.get('status')).toEqual('ready,error')
        expect(url.searchParams.get('author')).toEqual('alice@acme.com')
        expect(url.searchParams.get('ordering')).toEqual('-created_at')
        expect(url.searchParams.get('limit')).toEqual('50')
        expect(url.searchParams.get('offset')).toEqual('0')
    })

    it('resets `page` to 1 when filters change', async () => {
        await expectLogic(logic, () => {
            logic.actions.setFilters({ page: 3 })
        }).toMatchValues({ filters: expect.objectContaining({ page: 3 }) })

        await expectLogic(logic, () => {
            logic.actions.setFilters({ search: 'something' })
        }).toMatchValues({ filters: expect.objectContaining({ page: 1, search: 'something' }) })
    })

    it('redeployDeployment calls the nested redeploy endpoint then reloads', async () => {
        const redeploySpy = jest.fn(
            () =>
                [201, makeDeployment('new-redeploy', { status: 'queued', trigger_kind: 'redeploy' })] as [
                    number,
                    DeploymentApi,
                ]
        )
        useMocks({
            post: {
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/redeploy/': redeploySpy,
            },
        })

        await expectLogic(logic, () => {
            logic.actions.redeployDeployment('project-1-d1')
        }).toFinishAllListeners()

        expect(redeploySpy).toHaveBeenCalled()
        const calledReq = (redeploySpy.mock.calls[0] as unknown as [{ params: Record<string, string> }])[0]
        expect(calledReq.params.project_id).toEqual(projectA.id)
        expect(calledReq.params.id).toEqual('project-1-d1')
    })

    it('rollbackDeployment calls the nested rollback endpoint then reloads', async () => {
        const rollbackSpy = jest.fn(
            () =>
                [201, makeDeployment('new-rollback', { status: 'ready', trigger_kind: 'rollback' })] as [
                    number,
                    DeploymentApi,
                ]
        )
        useMocks({
            post: {
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/rollback/': rollbackSpy,
            },
        })

        await expectLogic(logic, () => {
            logic.actions.rollbackDeployment('project-1-d1')
        }).toFinishAllListeners()

        expect(rollbackSpy).toHaveBeenCalled()
        const calledReq = (rollbackSpy.mock.calls[0] as unknown as [{ params: Record<string, string> }])[0]
        expect(calledReq.params.project_id).toEqual(projectA.id)
        expect(calledReq.params.id).toEqual('project-1-d1')
    })

    it('pushes filters into the project URL when set', async () => {
        await expectLogic(logic, () => {
            logic.actions.setFilters({ search: 'feat', status: ['ready', 'error'] })
        }).toFinishAllListeners()

        expect(router.values.location.pathname).toEqual(`/deployments/${projectA.id}`)
        expect(router.values.searchParams.search).toEqual('feat')
        expect(router.values.searchParams.status).toEqual('ready,error')
    })
})
