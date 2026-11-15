import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { accessDetailLogic } from './accessDetailLogic'
import { addPropertyRestrictionModalLogic } from './addPropertyRestrictionModalLogic'
import { AddPropertyRuleModal } from './AddPropertyRuleModal'

describe('AddPropertyRuleModal', () => {
    const props = { projectId: '997', scopeType: 'default' as const, subjectId: '' }
    let logic: ReturnType<typeof addPropertyRestrictionModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:id/access_control_default_objects': { results: [] },
                '/api/projects/:id/access_control_default_properties': { results: [] },
                '/api/projects/:id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
        logic = addPropertyRestrictionModalLogic.build(props)
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([200, 500])('prevents dismissal until a save completes with status %s', async (status) => {
        let releaseSave: () => void = () => {}
        const pendingSave = new Promise<void>((resolve) => {
            releaseSave = resolve
        })
        useMocks({
            post: {
                '/api/projects/:id/property_access_controls/': async () => {
                    await pendingSave
                    return [status, status === 200 ? { id: 'new-rule', access_level: 'read' } : { detail: 'Try again' }]
                },
            },
        })
        const user = userEvent.setup()
        render(<AddPropertyRuleModal {...props} />)
        await act(async () => {
            await expectLogic(logic, () => {
                logic.actions.openModal()
                logic.actions.setPropertyType('ai')
            }).toDispatchActions(['loadPropertyOptionsSuccess'])
        })
        act(() => logic.actions.setPropertyId('$ai_output_choices'))
        await user.click(screen.getByText('Add rule'))

        const cancel = screen.getByText('Cancel').closest('button')!
        const dialog = screen.getByRole('dialog')
        expect(cancel).toHaveAttribute('aria-disabled', 'true')
        expect(screen.queryByLabelText('close')).not.toBeInTheDocument()
        fireEvent.click(cancel)
        fireEvent.keyDown(dialog, { key: 'Escape', code: 'Escape', keyCode: 27 })
        fireEvent.click(dialog.parentElement!)
        expect(dialog).toBeVisible()
        expect(logic.values.isOpen).toBe(true)

        await act(async () => {
            await expectLogic(accessDetailLogic(props), releaseSave).toDispatchActions(['ruleSaveFinished'])
        })
        if (status === 500) {
            expect(dialog).toBeVisible()
            expect(cancel).not.toHaveAttribute('aria-disabled', 'true')
            expect(screen.getByLabelText('close')).toBeVisible()
            await user.click(cancel)
        }
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })
})
