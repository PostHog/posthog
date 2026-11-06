import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { actionsLogic } from '~/toolbar/shared/actions/actionsLogic'
import { actionsTabLogic } from '~/toolbar/shared/actions/actionsTabLogic'
import { toolbarLogic } from '~/toolbar/shared/bar/toolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'

// The toolbar logger mirrors intentional error/auth paths to the console (its job on
// customer pages); tests exercise those paths on purpose, so stub the boundary.
jest.mock('~/toolbar/shared/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const mockAction = {
    id: 42,
    name: 'Test Action',
    steps: [],
    created_at: '',
    created_by: null,
    pinned_at: null,
}

describe('actionsTabLogic form submission', () => {
    // These suites intentionally reject requests to exercise error states; the
    // failures are asserted via authStatus/values, so skip the global loader logging.
    beforeAll(silenceKeaLoadersErrors)
    afterAll(resumeKeaLoadersErrors)

    let logic: ReturnType<typeof actionsTabLogic.build>

    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic
            .build({
                apiURL: 'http://localhost',
                accessToken: 'test-token',
                refreshToken: 'test-refresh',
                clientId: 'test-client',
            })
            .mount()
        toolbarLogic().mount()
        actionsLogic().mount()
        logic = actionsTabLogic()
        logic.mount()
    })

    it('creates a new action via POST', async () => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: true,
                json: () => Promise.resolve(mockAction),
            } as any as Response)
        )

        logic.actions.newAction()
        logic.actions.setActionFormValue('name', 'Test Action')

        await expectLogic(logic, () => {
            logic.actions.submitActionForm()
        })
            .delay(0)
            .toDispatchActions(['submitActionForm', 'submitActionFormSuccess'])

        expect(global.fetch).toHaveBeenCalledWith(
            expect.stringContaining('/api/projects/@current/actions/'),
            expect.objectContaining({ method: 'POST' })
        )
    })

    it('updates an existing action via PATCH', async () => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: true,
                json: () => Promise.resolve(mockAction),
            } as any as Response)
        )

        logic.actions.selectAction(42)
        logic.actions.setActionFormValue('name', 'Updated Action')

        await expectLogic(logic, () => {
            logic.actions.submitActionForm()
        })
            .delay(0)
            .toDispatchActions(['submitActionForm', 'submitActionFormSuccess'])

        expect(global.fetch).toHaveBeenCalledWith(
            expect.stringContaining('/api/projects/@current/actions/42/'),
            expect.objectContaining({ method: 'PATCH' })
        )
    })

    it('handles error response with detail message', async () => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: false,
                status: 400,
                json: () => Promise.resolve({ detail: 'Validation error' }),
            } as any as Response)
        )

        logic.actions.newAction()
        logic.actions.setActionFormValue('name', 'Bad Action')

        await expectLogic(logic, () => {
            logic.actions.submitActionForm()
        })
            .delay(0)
            .toDispatchActions(['submitActionForm', 'submitActionFormFailure'])
            .toNotHaveDispatchedActions(['submitActionFormSuccess'])
    })

    it('shows a duplicate name error from the server on the name field', async () => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: false,
                status: 400,
                json: () =>
                    Promise.resolve({
                        type: 'validation_error',
                        code: 'unique',
                        attr: 'name',
                        detail: 'This project already has an action with this name, ID 7',
                    }),
            } as any as Response)
        )

        logic.actions.newAction()
        logic.actions.setActionFormValue('name', 'Taken Name')

        await expectLogic(logic, () => {
            logic.actions.submitActionForm()
        })
            .delay(0)
            .toDispatchActions(['submitActionForm', 'setActionFormManualErrors', 'submitActionFormFailure'])
            .toNotHaveDispatchedActions(['submitActionFormSuccess'])

        expect(logic.values.actionFormErrors.name).toBe(
            'An action with this name already exists. Pick a different name.'
        )
    })

    it.each([
        ['blocks a new action that reuses an existing name', 'new' as const, false],
        ['allows an existing action to keep its own name', 42, true],
    ])('%s', async (_, actionId, shouldSave) => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: true,
                json: () => Promise.resolve(mockAction),
            } as any as Response)
        )
        actionsLogic.actions.updateAction({ action: mockAction as any })

        if (actionId === 'new') {
            logic.actions.newAction()
        } else {
            logic.actions.selectAction(actionId)
        }
        logic.actions.setActionFormValue('name', mockAction.name)
        expect(logic.values.actionFormValidationErrors.name).toBe(
            shouldSave ? undefined : 'An action with this name already exists. Pick a different name.'
        )

        logic.actions.submitActionForm()
        await expectLogic(logic).delay(0)
        expect(global.fetch).toHaveBeenCalledTimes(shouldSave ? 1 : 0)
    })

    it('handles error response when json parsing fails', async () => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: false,
                status: 500,
                json: () => Promise.reject(new Error('parse error')),
            } as any as Response)
        )

        logic.actions.newAction()
        logic.actions.setActionFormValue('name', 'Server Error Action')

        await expectLogic(logic, () => {
            logic.actions.submitActionForm()
        })
            .delay(0)
            .toDispatchActions(['submitActionForm', 'submitActionFormFailure'])
            .toNotHaveDispatchedActions(['submitActionFormSuccess'])
    })

    it('sets creation_context when automatic action creation is enabled', async () => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: true,
                json: () => Promise.resolve(mockAction),
            } as any as Response)
        )

        logic.actions.setAutomaticActionCreationEnabled(true, 'Auto Action')
        logic.actions.newAction()

        await expectLogic(logic, () => {
            logic.actions.submitActionForm()
        })
            .delay(0)
            .toDispatchActions(['submitActionForm', 'submitActionFormSuccess'])

        const fetchCall = (global.fetch as jest.Mock).mock.calls[0]
        const body = JSON.parse(fetchCall[1].body)
        expect(body.creation_context).toBe('onboarding')
    })
})
