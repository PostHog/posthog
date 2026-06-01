import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { Scene } from 'scenes/sceneTypes'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { deploymentLogic } from './deploymentLogic'
import { deploymentProjectLogic } from './deploymentProjectLogic'
import { deploymentsLogic } from './deploymentsLogic'
import { makeDeployment, makeProject } from './testHelpers'

const project = makeProject('project-1', 'Site', { current_deployment: 'dep-current' })

const deployments = [
    makeDeployment('dep-current', {
        commit_sha: '7a3f9c2',
        commit_message: 'feat: ship deployments',
        deployment_url: 'https://site-dep-current.pages.dev',
        cloudflare_deployment_id: 'cf-1',
        is_current: true,
    }),
]

describe('deploymentLogic', () => {
    let listLogic: ReturnType<typeof deploymentsLogic.build>
    let projectLogic: ReturnType<typeof deploymentProjectLogic.build>

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

        projectLogic = deploymentProjectLogic({ projectId: project.id })
        projectLogic.mount()
        await expectLogic(projectLogic).toFinishAllListeners()
    })

    afterEach(() => {
        projectLogic?.unmount()
        listLogic?.unmount()
    })

    it('fetches the deployment by id from the retrieve endpoint', async () => {
        const detail = deploymentLogic({ projectId: project.id, id: 'dep-current' })
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
        const detail = deploymentLogic({ projectId: project.id, id: 'does-not-exist' })
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

    it('builds breadcrumbs: Deployments → project name → commit message (or fallback)', async () => {
        const found = deploymentLogic({ projectId: project.id, id: 'dep-current' })
        found.mount()
        try {
            await expectLogic(found).toFinishAllListeners()
            const crumbs = found.values.breadcrumbs
            expect(crumbs).toHaveLength(3)
            expect(crumbs[0]).toMatchObject({ key: Scene.Deployments, name: 'Deployments' })
            expect(crumbs[1]).toMatchObject({ name: project.name })
            expect(crumbs[2]).toMatchObject({ name: 'feat: ship deployments' })
        } finally {
            found.unmount()
        }

        const missing = deploymentLogic({ projectId: project.id, id: 'does-not-exist' })
        missing.mount()
        try {
            await expectLogic(missing).toFinishAllListeners()
            const crumbs = missing.values.breadcrumbs
            // Falls back to 'Deployment' literal when retrieve returns no row.
            expect(crumbs[2]).toMatchObject({ name: 'Deployment' })
        } finally {
            missing.unmount()
        }
    })

    it('deep-link: loads the deployment without waiting on a project list mount', async () => {
        // Simulate a cold start — neither the list logic nor the project logic
        // have been mounted yet. The detail logic should still fetch via its
        // own props (projectId + id come from paramsToProps in the route).
        projectLogic.unmount()
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

        const detail = deploymentLogic({ projectId: project.id, id: 'dep-current' })
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
