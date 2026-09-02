import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { accountsSupportTicketsList } from 'products/customer_analytics/frontend/generated/api'
import type { SupportTicketApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountSupportTicketsLogic } from './accountSupportTicketsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics call other generated
    // functions on mount, and an absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsSupportTicketsList: jest.fn(),
}))

const mockList = accountsSupportTicketsList as jest.MockedFunction<typeof accountsSupportTicketsList>

describe('accountSupportTicketsLogic', () => {
    let logic: ReturnType<typeof accountSupportTicketsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mount = async (): Promise<void> => {
        logic = accountSupportTicketsLogic({ accountId: 'acc-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('loads the account tickets', async () => {
        const tickets = [{ id: 't-1', ticket_number: 7, status: 'open' }] as SupportTicketApi[]
        mockList.mockResolvedValue(tickets)

        await mount()

        expect(logic.values.ticketsResult).toEqual({ tickets })
    })

    it('surfaces a load-failed result (not an infinite skeleton) and captures the error when the fetch throws', async () => {
        mockList.mockRejectedValue(new Error('network'))

        await mount()

        expect(logic.values.ticketsResult).toEqual({ tickets: null, loadFailed: true })
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })
})
