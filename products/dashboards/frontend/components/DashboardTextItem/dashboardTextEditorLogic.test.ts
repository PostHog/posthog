import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dashboardTextEditorLogic } from './dashboardTextEditorLogic'

describe('dashboardTextEditorLogic', () => {
    beforeEach(() => initKeaTests())

    it('shows field validation without reporting an API failure for an empty card', async () => {
        const onSaved = jest.fn()
        const logic = dashboardTextEditorLogic({ dashboardId: 99, tileId: 7, initialBody: 'Saved text', onSaved })
        logic.mount()
        logic.actions.setTextValue('body', ' ')
        await expectLogic(logic, () => logic.actions.submitText()).toFinishAllListeners()
        expect(logic.values.textValidationErrors.body).toBeTruthy()
        expect(logic.values.saveFailed).toBe(false)
        expect(onSaved).not.toHaveBeenCalled()
        logic.unmount()
    })

    it('keeps the draft open until a successful save and retries failures without changing other text settings', async () => {
        const onSaved = jest.fn()
        const logic = dashboardTextEditorLogic({ dashboardId: 99, tileId: 7, initialBody: 'Saved text', onSaved })
        logic.mount()
        const requests: unknown[] = []
        let release: (() => void) | undefined
        const pending = new Promise<void>((resolve) => {
            release = resolve
        })
        let fail = true
        useMocks({
            post: {
                '/api/projects/:team_id/dashboards/99/update_text_tile/': async ({ request }) => {
                    requests.push(await request.json())
                    await pending
                    return fail ? [500, { detail: 'Save failed' }] : { id: 7, text: { id: 11, body: 'Revised text' } }
                },
            },
        })
        logic.actions.setTextValue('body', 'Revised text')
        const saving = expectLogic(logic, () => logic.actions.submitText()).toFinishAllListeners()
        await waitFor(() => expect(requests).toHaveLength(1))
        expect(onSaved).not.toHaveBeenCalled()
        expect(logic.values.isTextSubmitting).toBe(true)
        release!()
        await saving
        expect(onSaved).not.toHaveBeenCalled()
        expect(logic.values.text.body).toBe('Revised text')
        expect(logic.values.saveFailed).toBe(true)
        fail = false
        await expectLogic(logic, () => logic.actions.submitText()).toFinishAllListeners()
        expect(onSaved).toHaveBeenCalledWith({ id: 11, body: 'Revised text' })
        expect(requests).toEqual([
            { tile_id: 7, body: 'Revised text' },
            { tile_id: 7, body: 'Revised text' },
        ])
        logic.unmount()
    })
})
