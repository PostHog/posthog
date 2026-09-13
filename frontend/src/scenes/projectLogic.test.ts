import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { organizationLogic } from './organizationLogic'
import { projectLogic } from './projectLogic'

describe('projectLogic', () => {
    let logic: ReturnType<typeof projectLogic.build>

    describe('createProject', () => {
        const newProject = {
            ...MOCK_DEFAULT_PROJECT,
            id: MOCK_DEFAULT_PROJECT.id + 1,
            name: 'Brand new project',
        }

        beforeEach(() => {
            useMocks({
                post: {
                    '/api/projects/': () => [200, newProject],
                },
                get: {
                    '/api/organizations/@current': () => [
                        200,
                        {
                            ...MOCK_DEFAULT_ORGANIZATION,
                            teams: [...MOCK_DEFAULT_ORGANIZATION.teams!, newProject],
                            projects: [...MOCK_DEFAULT_ORGANIZATION.projects!, newProject],
                        },
                    ],
                },
            })
            initKeaTests()
            logic = projectLogic()
            logic.mount()
            organizationLogic.mount()
        })

        it('refreshes currentOrganization so the new project appears without a page reload', async () => {
            expect(organizationLogic.values.currentOrganization?.teams?.map((t) => t.id)).toEqual([
                MOCK_DEFAULT_PROJECT.id,
            ])

            await expectLogic(logic, () => {
                logic.actions.createProject({ name: 'Brand new project' })
            }).toDispatchActions([
                'createProjectSuccess',
                organizationLogic.actionTypes.loadCurrentOrganization,
                organizationLogic.actionTypes.loadCurrentOrganizationSuccess,
            ])

            expect(organizationLogic.values.currentOrganization?.id).toBe(MOCK_ORGANIZATION_ID)
            expect(organizationLogic.values.currentOrganization?.teams?.map((t) => t.id)).toEqual([
                MOCK_DEFAULT_PROJECT.id,
                newProject.id,
            ])
        })
    })
})
