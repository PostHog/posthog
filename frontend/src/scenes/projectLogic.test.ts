import { MOCK_DEFAULT_PROJECT, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

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

    it('loadCurrentProject reloads the tab project after another tab changes the current project', async () => {
        initKeaTests()
        const logic = projectLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCurrentProjectSuccess'])
        useMocks({
            get: {
                '/api/projects/@current': () => [200, { ...MOCK_DEFAULT_PROJECT, id: MOCK_DEFAULT_PROJECT.id + 1 }],
                '/api/projects/:id': ({ params }) =>
                    params.id === String(MOCK_DEFAULT_PROJECT.id)
                        ? [200, { ...MOCK_DEFAULT_PROJECT, name: 'Reloaded project' }]
                        : [404, {}],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadCurrentProject()
        }).toDispatchActions(['loadCurrentProjectSuccess'])

        expect(logic.values.currentProject?.id).toBe(MOCK_DEFAULT_PROJECT.id)
        expect(logic.values.currentProject?.name).toBe('Reloaded project')
    })

    it.each([
        ['/project/997/insights', false],
        ['/project/997/my-tickets', true],
    ])('on a project pending deletion, %s stays open: %s', async (path, staysOpen) => {
        initKeaTests()
        router.actions.push(path)
        const logic = projectLogic()
        logic.mount()

        logic.actions.loadCurrentProjectSuccess({ ...MOCK_DEFAULT_PROJECT, is_pending_deletion: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname === path).toBe(staysOpen)
    })

    it.each([
        ['createProject', 'createProjectFailure'],
        ['updateCurrentProject', 'updateCurrentProjectFailure'],
    ] as const)('%s toasts a duplicate name 409 and does not report it', async (actionName, failureAction) => {
        const detail = 'There is already a project called "Taken" in this organization. Choose a different name.'
        useMocks({
            post: { '/api/projects/': () => [409, { type: 'validation_error', code: 'conflict', detail }] },
            patch: { '/api/projects/:id': () => [409, { type: 'validation_error', code: 'conflict', detail }] },
        })
        initKeaTests()
        const logic = projectLogic()
        logic.mount()
        logic.actions.loadCurrentProjectSuccess(MOCK_DEFAULT_PROJECT)
        const toastError = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        const captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
        try {
            await expectLogic(logic, () => {
                if (actionName === 'createProject') {
                    logic.actions.createProject({ name: 'Taken' })
                } else {
                    logic.actions.updateCurrentProject({ name: 'Taken' })
                }
            }).toDispatchActions([failureAction])

            expect(toastError).toHaveBeenCalledWith(detail)
            expect(captureException).not.toHaveBeenCalled()
        } finally {
            toastError.mockRestore()
            captureException.mockRestore()
        }
    })
})
