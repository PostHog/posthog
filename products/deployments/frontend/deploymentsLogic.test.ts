import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { deploymentsLogic } from './deploymentsLogic'
import type { DeploymentApi, DeploymentProjectApi } from './generated/api.schemas'

const makeProject = (
    id: string,
    name: string,
    currentDeployment: string | null = `${id}-d1`
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
    current_deployment: currentDeployment,
    is_ready_to_deploy: true,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
})

const makeDeployment = (id: string, overrides: Partial<DeploymentApi> = {}): DeploymentApi => ({
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

describe('deploymentsLogic (grid)', () => {
    let logic: ReturnType<typeof deploymentsLogic.build>

    const projectA = makeProject('project-1', 'Site')
    const projectB = makeProject('project-2', 'Docs')

    beforeEach(async () => {
        initKeaTests()

        useMocks({
            get: {
                '/api/projects/:team/deployment_projects/': () => [
                    200,
                    { count: 2, next: null, previous: null, results: [projectA, projectB] },
                ],
                '/api/projects/:team/deployment_projects/:project_id/deployments/': (req) => [
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
                ],
            },
        })

        router.actions.push('/deployments')

        logic = deploymentsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the project list on mount', () => {
        expect(logic.values.deploymentProjects.map((p) => p.id)).toEqual([projectA.id, projectB.id])
        expect(logic.values.hasNoProjects).toBe(false)
    })

    it('fans out one current-deployment fetch per project for the grid', () => {
        expect(Object.keys(logic.values.currentDeploymentsByProject).sort()).toEqual([projectA.id, projectB.id].sort())
        expect(logic.values.currentDeploymentsByProject[projectA.id]?.id).toEqual(`${projectA.id}-d1`)
        expect(logic.values.currentDeploymentsByProject[projectB.id]?.id).toEqual(`${projectB.id}-d1`)
    })

    it('opens and closes the Add Project modal via reducer', async () => {
        expect(logic.values.addProjectModalOpen).toBe(false)
        await expectLogic(logic, () => {
            logic.actions.openAddProjectModal()
        }).toMatchValues({ addProjectModalOpen: true })
        await expectLogic(logic, () => {
            logic.actions.closeAddProjectModal()
        }).toMatchValues({ addProjectModalOpen: false })
    })

    it('reports hasNoProjects when the team has zero projects', async () => {
        useMocks({
            get: {
                '/api/projects/:team/deployment_projects/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadDeploymentProjects()
        }).toFinishAllListeners()
        expect(logic.values.hasNoProjects).toBe(true)
    })
})
