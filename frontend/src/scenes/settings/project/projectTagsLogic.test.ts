import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { projectTagsLogic } from './projectTagsLogic'

describe('projectTagsLogic', () => {
    const savedProject = { ...MOCK_DEFAULT_PROJECT, tags: ['keep', 'project-group:production'] }
    let requests: { tags: string[] }[]

    beforeEach(async () => {
        requests = []
        useMocks({
            patch: {
                '/api/projects/:id': async ({ request }) => {
                    const payload = (await request.json()) as { tags: string[] }
                    requests.push(payload)
                    return [200, { ...savedProject, ...payload }]
                },
            },
        })
        initKeaTests()
        projectTagsLogic.mount()
        await expectLogic(organizationLogic).toFinishAllListeners()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: OrganizationMembershipLevel.Admin,
        })
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Member,
        })
        projectLogic.actions.loadCurrentProjectSuccess(savedProject)
    })

    test.each(['中文', '---'])('rejects the nonempty invalid group name %s without replacing tags', async (name) => {
        projectTagsLogic.actions.setProjectGroupValue('name', name)
        expect(projectTagsLogic.values.projectGroupHasErrors).toBe(true)
        expect(projectTagsLogic.values.projectGroupValidationErrors.name).toBeTruthy()

        await expectLogic(projectTagsLogic, () => {
            projectTagsLogic.actions.submitProjectGroup()
        }).toFinishAllListeners()

        expect(requests).toEqual([])
        expect(projectLogic.values.currentProject?.tags).toEqual(savedProject.tags)
    })

    it('keeps the draft and clears the submitting state when the API rejects a group change', async () => {
        useMocks({ patch: { '/api/projects/:id': () => [400, { detail: 'The project group could not be saved.' }] } })
        projectTagsLogic.actions.setProjectGroupValue('name', 'staging')

        await expectLogic(projectTagsLogic, () => {
            projectTagsLogic.actions.submitProjectGroup()
        }).toDispatchActions(['submitProjectGroupFailure'])

        expect(projectTagsLogic.values.projectGroup.name).toBe('staging')
        expect(projectTagsLogic.values.isProjectGroupSubmitting).toBe(false)
        expect(projectLogic.values.currentProject?.tags).toEqual(savedProject.tags)
    })

    test.each([
        { name: 'staging apps', tags: ['keep', 'project-group:staging-apps'], savedName: 'staging-apps' },
        { name: '', tags: ['keep'], savedName: '' },
    ])('saves "$name" while preserving regular tags', async ({ name, tags, savedName }) => {
        projectTagsLogic.actions.setProjectGroupValue('name', name)

        await expectLogic(projectTagsLogic, () => {
            projectTagsLogic.actions.submitProjectGroup()
        }).toDispatchActions(['submitProjectGroupSuccess'])

        expect(requests).toEqual([{ tags }])
        expect(projectTagsLogic.values.projectGroup.name).toBe(savedName)
        expect(projectTagsLogic.values.isProjectGroupSubmitting).toBe(false)
    })
})
