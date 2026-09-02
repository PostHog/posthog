import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import { editConversationsWidgetModalLogic } from './editConversationsWidgetModalLogic'

describe('editConversationsWidgetModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('reports a save failure and permits retry', async () => {
        const onSave = jest
            .fn()
            .mockRejectedValueOnce(new Error('Network unavailable'))
            .mockResolvedValueOnce(undefined)
        const onClose = jest.fn()
        const errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
        const logic = editConversationsWidgetModalLogic({
            config: { limit: 10, status: 'all' },
            onSave,
            onClose,
            defaultTitle: 'Recent tickets',
        })
        logic.mount()

        await expectLogic(logic, () => logic.actions.submit())
            .toFinishAllListeners()
            .toMatchValues({ saving: false })
        expect(onClose).not.toHaveBeenCalled()
        expect(errorToast).toHaveBeenCalledWith('Could not save widget settings. Check your connection and try again.')

        await expectLogic(logic, () => logic.actions.submit())
            .toFinishAllListeners()
            .toMatchValues({ saving: false })
        expect(onClose).toHaveBeenCalledTimes(1)
        logic.unmount()
    })
})
