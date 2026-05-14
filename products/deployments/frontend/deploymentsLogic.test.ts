import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { deploymentsLogic } from './deploymentsLogic'
import { makeDeployment, makeProject } from './testHelpers'

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
                // Each fixture project has a `current_deployment` set by
                // `makeProject`, so the grid's fan-out takes the
                // retrieve-by-id path. List is the fallback for
                // never-deployed projects — mocked too so tests that null
                // out `current_deployment` still resolve.
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/': (req) => [
                    200,
                    makeDeployment(String(req.params.id), {
                        project: String(req.params.project_id),
                        is_current: true,
                    }),
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
