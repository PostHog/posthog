import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

const mockAction = {
    id: 42,
    name: 'Test Action',
    steps: [],
    created_at: '',
    created_by: null,
    pinned_at: null,
}

describe('actionsTabLogic form submission', () => {
    let logic: ReturnType<typeof actionsTabLogic.build>

    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic.build({ apiURL: 'http://localhost' }).mount()
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
