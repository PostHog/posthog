import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import { conversationsTicketsPartialUpdate } from 'products/conversations/frontend/generated/api'

import { conversationsWidgetLogic } from './conversationsWidgetLogic'

jest.mock('products/conversations/frontend/generated/api', () => ({
    conversationsTicketsPartialUpdate: jest.fn(),
}))

describe('conversationsWidgetLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('updates the assignee and refreshes the tile', async () => {
        const refresh = jest.fn()
        const update = conversationsTicketsPartialUpdate as jest.Mock
        update.mockResolvedValue({})
        const logic = conversationsWidgetLogic({ tileId: 1, onRefreshData: refresh })
        logic.mount()

        await expectLogic(logic, () => logic.actions.assignTicket('ticket-1', { type: 'user', id: 3 }))
            .toFinishAllListeners()
            .toMatchValues({ ticketAssignmentLoadingId: null })

        expect(update).toHaveBeenCalledWith(expect.any(String), 'ticket-1', {
            assignee: { type: 'user', id: 3 },
        })
        expect(refresh).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it('shows an error and permits another assignment after a failed request', async () => {
        const errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
        const update = conversationsTicketsPartialUpdate as jest.Mock
        update.mockRejectedValue(new Error('Network unavailable'))
        const logic = conversationsWidgetLogic({ tileId: 1 })
        logic.mount()

        await expectLogic(logic, () => logic.actions.assignTicket('ticket-1', null))
            .toFinishAllListeners()
            .toMatchValues({ ticketAssignmentLoadingId: null })

        expect(errorToast).toHaveBeenCalledWith('Could not update the assignee. Try again.')
        logic.unmount()
    })
})
