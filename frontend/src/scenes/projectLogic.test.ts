import { MOCK_DEFAULT_PROJECT, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { organizationLogic } from './organizationLogic'
import { projectLogic } from './projectLogic'

describe('projectLogic', () => {
    it('captures project setting changes without event usage logic', async () => {
        useMocks({
            patch: {
                '/api/projects/:id': () => [200, { ...MOCK_DEFAULT_PROJECT, name: 'New project name' }],
            },
        })
        initKeaTests()
        const logic = projectLogic()
        logic.mount()
        logic.actions.loadCurrentProjectSuccess(MOCK_DEFAULT_PROJECT)
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        try {
            await expectLogic(logic, () => {
                logic.actions.updateCurrentProject({ name: 'New project name' })
            }).toDispatchActions(['updateCurrentProjectSuccess'])

            expect(capture).toHaveBeenCalledWith('name project setting updated', {
                setting: 'name',
                value: 'New project name',
            })
        } finally {
            capture.mockRestore()
        }
    })

    it('cancels project deletion in the current organization when the project has no organization_id', async () => {
        const requestedOrganizationIds: string[] = []
        useMocks({
            post: {
                '/api/organizations/:organizationId/projects/:id/cancel-deletion/': (req) => {
                    requestedOrganizationIds.push(req.params.organizationId as string)
                    return [200, { ...MOCK_DEFAULT_PROJECT, is_pending_deletion: false }]
                },
            },
        })
        initKeaTests()
        const logic = projectLogic()
        logic.mount()
        await expectLogic(organizationLogic).toFinishAllListeners()

        const { organization_id: _, ...projectFromCurrentEndpoint } = MOCK_DEFAULT_PROJECT
        logic.actions.loadCurrentProjectSuccess({
            ...projectFromCurrentEndpoint,
            is_pending_deletion: true,
        } as typeof MOCK_DEFAULT_PROJECT)

        await expectLogic(logic, () => {
            logic.actions.cancelProjectDeletion()
        }).toDispatchActions(['cancelProjectDeletionSuccess'])

        expect(requestedOrganizationIds).toEqual([MOCK_ORGANIZATION_ID])
    })
})
